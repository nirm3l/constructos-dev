#!/usr/bin/env python3
"""
Lightweight QA smoke runner intended to be executed inside the `task-app` container:

  docker compose exec -T task-app python scripts/qa_smoke.py

It runs a handful of end-to-end API checks on a clean environment and files any
failures as BUG tasks in the `m4trix` project.
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx


BASE_URL = "http://127.0.0.1:8000"
DEFAULT_USERNAME = os.getenv("QA_USERNAME", "admin")
DEFAULT_PASSWORD = os.getenv("QA_PASSWORD", "admin")


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


@dataclass
class Bug:
    title: str
    steps: str
    expected: str
    actual: str
    evidence: str = ""


class Api:
    def __init__(self) -> None:
        self.c = httpx.Client(timeout=30.0)
        login = self.c.post(
            BASE_URL + "/api/auth/login",
            json={"username": DEFAULT_USERNAME, "password": DEFAULT_PASSWORD},
        )
        login.raise_for_status()

    def close(self) -> None:
        self.c.close()

    def get_json(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        r = self.c.get(BASE_URL + path, params=params)
        r.raise_for_status()
        return r.json()

    def post_json(self, path: str, payload: dict[str, Any]) -> Any:
        r = self.c.post(BASE_URL + path, json=payload)
        r.raise_for_status()
        return r.json()

    def patch_json(self, path: str, payload: dict[str, Any]) -> Any:
        r = self.c.patch(BASE_URL + path, json=payload)
        r.raise_for_status()
        return r.json()

    def post_raw(self, path: str, payload: dict[str, Any]) -> httpx.Response:
        return self.c.post(BASE_URL + path, json=payload)


def ensure_m4trix_project(api: Api, workspace_id: str) -> str:
    boot = api.get_json("/api/bootstrap")
    for p in boot.get("projects", []):
        if (p.get("workspace_id") == workspace_id) and (p.get("name") or "").strip().lower() == "m4trix":
            return p["id"]
    created = api.post_json(
        "/api/projects",
        {"workspace_id": workspace_id, "name": "m4trix", "description": "QA bug reports"},
    )
    return created["id"]


def create_bug_task(api: Api, *, workspace_id: str, project_id: str, bug: Bug) -> str:
    desc = (
        f"Steps to reproduce:\n{bug.steps}\n\n"
        f"Expected:\n{bug.expected}\n\n"
        f"Actual:\n{bug.actual}\n"
    )
    if bug.evidence:
        desc += f"\nEvidence:\n{bug.evidence}\n"
    created = api.post_json(
        "/api/tasks",
        {
            "workspace_id": workspace_id,
            "project_id": project_id,
            "title": f"BUG: {bug.title}",
            "description": desc,
            "priority": "High",
            "labels": ["bug", "qa"],
        },
    )
    return created["id"]


def main() -> int:
    bugs: list[Bug] = []
    api = Api()
    try:
        # Bootstrap sanity
        try:
            boot = api.get_json("/api/bootstrap")
            workspaces = boot.get("workspaces") or []
            if not workspaces:
                raise RuntimeError("bootstrap returned no workspaces")
            workspace_id = workspaces[0]["id"]
        except Exception as exc:
            bugs.append(
                Bug(
                    title="Bootstrap fails on clean environment",
                    steps="1. Start app\n2. Login as default user\n3. Call GET /api/bootstrap",
                    expected="200 OK with at least 1 workspace",
                    actual=f"Exception: {exc!r}",
                )
            )
            workspace_id = ""

        if not workspace_id:
            raise RuntimeError("Cannot proceed without workspace_id.")

        m4trix_project_id = ""
        try:
            m4trix_project_id = ensure_m4trix_project(api, workspace_id)
        except Exception as exc:
            bugs.append(
                Bug(
                    title="Creating m4trix project fails",
                    steps="1. POST /api/projects with {workspace_id, name: m4trix}",
                    expected="Project created and returned with id",
                    actual=f"Exception: {exc!r}",
                )
            )
            m4trix_project_id = ""

        # Tasks: create + patch persists
        task_id = ""
        try:
            default_project_id = (boot.get("projects") or [{}])[0].get("id") or ""
            created = api.post_json(
                "/api/tasks",
                {
                    "workspace_id": workspace_id,
                    "project_id": m4trix_project_id or default_project_id,
                    "title": "QA: task save smoke",
                    "description": "Initial description",
                    "priority": "Med",
                    "due_date": _iso(datetime.now(timezone.utc) + timedelta(days=2)),
                    "labels": ["qa"],
                    "recurring_rule": None,
                },
            )
            task_id = created["id"]
            api.patch_json(
                f"/api/tasks/{task_id}",
                {
                    "title": "QA: task save smoke (updated)",
                    "description": "Updated description",
                    "priority": "High",
                    "scheduled_instruction": "every:5m",
                },
            )
            listed = api.get_json("/api/tasks", params={"workspace_id": workspace_id, "q": "task save smoke (updated)"})
            items = listed.get("items") if isinstance(listed, dict) else listed
            if not items:
                raise RuntimeError("Updated task not found in list response.")
            row = items[0]
            if (row.get("description") or "") != "Updated description":
                raise RuntimeError(f"Description did not persist. got={row.get('description')!r}")
            if (row.get("priority") or "") != "High":
                raise RuntimeError(f"Priority did not persist. got={row.get('priority')!r}")
        except Exception as exc:
            bugs.append(
                Bug(
                    title="Task create/patch does not persist to list",
                    steps="1. Create task\n2. Patch title/description/priority\n3. GET /api/tasks?q=<updated>",
                    expected="Task appears with updated fields",
                    actual=f"Exception: {exc!r}",
                )
            )

        # Comments: create + list
        try:
            if not task_id:
                raise RuntimeError("No task_id from previous step.")
            # API expects CommentCreate: {body: "..."}
            api.post_json(f"/api/tasks/{task_id}/comments", {"body": "QA comment line 1\nline 2"})
            comments = api.get_json(f"/api/tasks/{task_id}/comments")
            if not isinstance(comments, list) or not comments:
                raise RuntimeError(f"Unexpected comments response: {comments!r}")
        except Exception as exc:
            bugs.append(
                Bug(
                    title="Task comments create/list fails",
                    steps="1. POST /api/tasks/{id}/comments\n2. GET /api/tasks/{id}/comments",
                    expected="Comment is returned in list",
                    actual=f"Exception: {exc!r}",
                )
            )

        # Notes: create + list + archive/restore
        note_ids: list[str] = []
        try:
            for i in range(3):
                n = api.post_json(
                    "/api/notes",
                    {
                        "workspace_id": workspace_id,
                        "project_id": m4trix_project_id or None,
                        "title": f"QA note {i+1}",
                        # API expects NoteCreate: {body: "..."}
                        "body": f"# Note {i+1}\n\nSome content.\n\n```js\nconsole.log({i})\n```\n",
                        "tags": ["qa", "smoke"],
                    },
                )
                note_ids.append(n["id"])
            listed = api.get_json("/api/notes", params={"workspace_id": workspace_id, "q": "QA note", "limit": 10})
            items = listed.get("items") if isinstance(listed, dict) else listed
            if not items or len(items) < 3:
                raise RuntimeError(f"Expected >=3 notes, got {len(items) if items else 0}")
            api.post_json(f"/api/notes/{note_ids[0]}/archive", {})
            archived = api.get_json("/api/notes", params={"workspace_id": workspace_id, "archived": True, "q": "QA note", "limit": 10})
            aitems = archived.get("items") if isinstance(archived, dict) else archived
            if not aitems:
                raise RuntimeError("Archived notes list is empty after archiving one note.")
            api.post_json(f"/api/notes/{note_ids[0]}/restore", {})
        except Exception as exc:
            bugs.append(
                Bug(
                    title="Notes create/list/archive/restore fails",
                    steps="1. Create 3 notes\n2. List notes\n3. Archive one\n4. List archived\n5. Restore",
                    expected="Notes persist and archive/restore changes list filters",
                    actual=f"Exception: {exc!r}",
                )
            )

        # Agent chat: bulk archive notes (should use archive_all_notes internally)
        try:
            if not note_ids:
                raise RuntimeError("No note_ids from previous step.")
            r = api.post_raw(
                "/api/agents/chat",
                {
                    "workspace_id": workspace_id,
                    "project_id": m4trix_project_id or None,
                    "instruction": "Archive all notes in this workspace.",
                    "history": [],
                    "session_id": "qa-smoke",
                },
            )
            if r.status_code != 200:
                raise RuntimeError(f"Chat returned {r.status_code}: {r.text[:400]}")
            data = r.json()
            if not data.get("ok", False):
                raise RuntimeError(f"Chat ok=false response: {data!r}")

            # Archive can take a moment; poll.
            deadline = time.time() + 8.0
            remaining = -1
            while time.time() < deadline:
                after = api.get_json("/api/notes", params={"workspace_id": workspace_id, "q": "QA note", "archived": False, "limit": 50})
                items = after.get("items") if isinstance(after, dict) else after
                remaining = len(items or [])
                if remaining == 0:
                    break
                time.sleep(0.5)
            if remaining != 0:
                raise RuntimeError(f"Some notes still unarchived after agent request. remaining={remaining}")
        except Exception as exc:
            bugs.append(
                Bug(
                    title="Agent chat cannot archive all notes",
                    steps="1. Create multiple notes\n2. POST /api/agents/chat: 'Archive all notes in this workspace'\n3. List unarchived notes",
                    expected="All notes become archived, and chat returns ok:true",
                    actual=f"Exception: {exc!r}",
                )
            )

        if bugs and m4trix_project_id:
            created_ids: list[str] = []
            for bug in bugs:
                try:
                    tid = create_bug_task(api, workspace_id=workspace_id, project_id=m4trix_project_id, bug=bug)
                    created_ids.append(tid)
                except Exception as exc:
                    print(f"FAILED to create bug task for: {bug.title} error={exc!r}", file=sys.stderr)
            if created_ids:
                print("Created bug tasks:", created_ids)

        if bugs:
            print(f"QA found {len(bugs)} issue(s).")
            for b in bugs:
                print("-", b.title)
            return 2

        print("QA smoke passed (no issues detected).")
        return 0
    finally:
        api.close()


if __name__ == "__main__":
    raise SystemExit(main())
