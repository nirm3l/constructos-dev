from __future__ import annotations

import mimetypes
import os
import re
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.core import Note, Project, Task, User, ensure_project_access, ensure_role, get_current_user, get_db
from shared.settings import ATTACHMENTS_DIR

router = APIRouter()


def _upload_root() -> Path:
    raw = os.getenv("ATTACHMENTS_DIR", ATTACHMENTS_DIR).strip() or ATTACHMENTS_DIR
    return Path(raw).expanduser().resolve()


def _safe_filename(name: str) -> str:
    base = Path(name or "upload.bin").name
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._")
    return cleaned or "upload.bin"


def _validate_scope(
    db: Session,
    *,
    workspace_id: str,
    project_id: str | None,
    task_id: str | None,
    note_id: str | None,
) -> tuple[str | None, str | None, str | None]:
    resolved_project_id = project_id
    resolved_task_id = task_id
    resolved_note_id = note_id

    if resolved_project_id:
        project = db.get(Project, resolved_project_id)
        if not project or project.is_deleted:
            raise HTTPException(status_code=404, detail="Project not found")
        if project.workspace_id != workspace_id:
            raise HTTPException(status_code=400, detail="Project does not belong to workspace")

    if resolved_task_id:
        task = db.execute(select(Task).where(Task.id == resolved_task_id, Task.is_deleted == False)).scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        if task.workspace_id != workspace_id:
            raise HTTPException(status_code=400, detail="Task does not belong to workspace")
        if resolved_project_id and task.project_id != resolved_project_id:
            raise HTTPException(status_code=400, detail="Task does not belong to project")
        if not resolved_project_id:
            resolved_project_id = task.project_id

    if resolved_note_id:
        note = db.execute(select(Note).where(Note.id == resolved_note_id, Note.is_deleted == False)).scalar_one_or_none()
        if not note:
            raise HTTPException(status_code=404, detail="Note not found")
        if note.workspace_id != workspace_id:
            raise HTTPException(status_code=400, detail="Note does not belong to workspace")
        if resolved_project_id and note.project_id != resolved_project_id:
            raise HTTPException(status_code=400, detail="Note does not belong to project")
        if not resolved_project_id:
            resolved_project_id = note.project_id

    if not (resolved_project_id or resolved_task_id or resolved_note_id):
        raise HTTPException(status_code=422, detail="At least one of project_id/task_id/note_id is required")

    return resolved_project_id, resolved_task_id, resolved_note_id


class AttachmentDeletePayload(BaseModel):
    workspace_id: str
    path: str


def _resolve_candidate(workspace_id: str, path: str) -> tuple[Path, Path]:
    upload_root = _upload_root()
    rel = Path(path)
    if rel.is_absolute():
        raise HTTPException(status_code=400, detail="Invalid path")
    candidate = (upload_root / rel).resolve()
    if not str(candidate).startswith(str(upload_root)):
        raise HTTPException(status_code=400, detail="Invalid path")
    expected_prefix = f"workspace/{workspace_id}/"
    if not path.startswith(expected_prefix):
        raise HTTPException(status_code=403, detail="Attachment does not belong to workspace")
    return upload_root, candidate


def _project_id_from_path(path: str) -> str | None:
    parts = [part for part in Path(path).as_posix().split("/") if part]
    if len(parts) >= 4 and parts[0] == "workspace" and parts[2] == "project":
        project_id = parts[3]
        if project_id and project_id != "_none":
            return project_id
    return None


@router.post("/api/attachments/upload")
async def upload_attachment(
    workspace_id: str = Form(...),
    project_id: str | None = Form(default=None),
    task_id: str | None = Form(default=None),
    note_id: str | None = Form(default=None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ensure_role(db, workspace_id, user.id, {"Owner", "Admin", "Member"})
    project_id, task_id, note_id = _validate_scope(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        task_id=task_id,
        note_id=note_id,
    )
    if project_id:
        ensure_project_access(db, workspace_id, project_id, user.id, {"Owner", "Admin", "Member"})

    owner_type = "project"
    owner_id = project_id
    if task_id:
        owner_type = "task"
        owner_id = task_id
    elif note_id:
        owner_type = "note"
        owner_id = note_id

    if not owner_id:
        raise HTTPException(status_code=422, detail="Unable to resolve owner id")

    safe_name = _safe_filename(file.filename or "upload.bin")
    stored_name = f"{uuid4()}_{safe_name}"
    upload_root = _upload_root()
    target_dir = upload_root / "workspace" / workspace_id / "project" / (project_id or "_none") / owner_type / owner_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / stored_name

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=422, detail="Empty file")
    target.write_bytes(raw)
    rel = target.relative_to(upload_root).as_posix()

    return {
        "path": rel,
        "name": safe_name,
        "mime_type": file.content_type or mimetypes.guess_type(safe_name)[0] or "application/octet-stream",
        "size_bytes": len(raw),
    }


@router.get("/api/attachments/download")
def download_attachment(
    workspace_id: str = Query(...),
    path: str = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ensure_role(db, workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
    _, candidate = _resolve_candidate(workspace_id, path)
    project_id = _project_id_from_path(path)
    if project_id:
        ensure_project_access(db, workspace_id, project_id, user.id, {"Owner", "Admin", "Member", "Guest"})
    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="Attachment not found")

    media_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
    return FileResponse(path=str(candidate), filename=candidate.name, media_type=media_type)


@router.post("/api/attachments/delete")
def delete_attachment(
    payload: AttachmentDeletePayload,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ensure_role(db, payload.workspace_id, user.id, {"Owner", "Admin", "Member"})
    upload_root, candidate = _resolve_candidate(payload.workspace_id, payload.path)
    project_id = _project_id_from_path(payload.path)
    if project_id:
        ensure_project_access(db, payload.workspace_id, project_id, user.id, {"Owner", "Admin", "Member"})
    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="Attachment not found")
    candidate.unlink(missing_ok=False)

    # Keep storage tidy: remove empty parent folders up to upload root.
    parent = candidate.parent
    while parent != upload_root:
        try:
            parent.rmdir()
        except OSError:
            break
        parent = parent.parent

    return {"ok": True}
