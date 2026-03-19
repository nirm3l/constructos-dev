from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from features.attachments import api as attachments_api


class _ExecuteResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeDb:
    def __init__(self, *, project=None, task=None, note=None):
        self._project = project
        self._task = task
        self._note = note

    def get(self, model, _id):
        if model is attachments_api.Project:
            return self._project
        return None

    def execute(self, _query):
        if self._note is not None:
            value = self._note
            self._note = None
            return _ExecuteResult(value)
        value = self._task
        self._task = None
        return _ExecuteResult(value)


def test_validate_scope_accepts_task_command_state_when_task_row_lags(monkeypatch):
    db = _FakeDb(
        project=SimpleNamespace(id="project-1", workspace_id="workspace-1", is_deleted=False),
        task=None,
    )
    monkeypatch.setattr(
        attachments_api,
        "load_task_command_state",
        lambda _db, task_id: SimpleNamespace(
            id=task_id,
            workspace_id="workspace-1",
            project_id="project-1",
            is_deleted=False,
        ),
    )

    project_id, task_id, note_id = attachments_api._validate_scope(
        db,
        workspace_id="workspace-1",
        project_id="project-1",
        task_id="task-1",
        note_id=None,
    )

    assert project_id == "project-1"
    assert task_id == "task-1"
    assert note_id is None


def test_validate_scope_rejects_missing_task_when_row_and_command_state_are_absent(monkeypatch):
    db = _FakeDb(project=None, task=None)
    monkeypatch.setattr(attachments_api, "load_task_command_state", lambda _db, _task_id: None)

    with pytest.raises(HTTPException) as exc_info:
        attachments_api._validate_scope(
            db,
            workspace_id="workspace-1",
            project_id=None,
            task_id="task-1",
            note_id=None,
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Task not found"
