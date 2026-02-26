#!/usr/bin/env python3
"""
Agent-chat focused QA checks (API-level). Files any failures as BUG tasks in `m4trix`.

Run inside container:
  docker compose exec -T task-app python scripts/qa_agents_chat.py
"""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx


BASE_URL = os.getenv("QA_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
DEFAULT_USERNAME = os.getenv("QA_USERNAME", "admin")
DEFAULT_PASSWORD = os.getenv("QA_PASSWORD", "admin")


@dataclass
class Bug:
    title: str
    steps: str
    expected: str
    actual: str
    evidence: str = ""


class Api:
    def __init__(self) -> None:
        self.c = httpx.Client(timeout=60.0)
        login = self.c.post(
            BASE_URL + "/api/auth/login",
            json={"username": DEFAULT_USERNAME, "password": DEFAULT_PASSWORD},
        )
        login.raise_for_status()

    def close(self) -> None:
        self.c.close()

    def req(self, method: str, path: str, *, params: dict[str, Any] | None = None, json_body: Any | None = None) -> httpx.Response:
        return self.c.request(method, BASE_URL + path, params=params, json=json_body)

    def json(self, method: str, path: str, *, params: dict[str, Any] | None = None, json_body: Any | None = None) -> Any:
        r = self.req(method, path, params=params, json_body=json_body)
        r.raise_for_status()
        return r.json()


def ensure_m4trix_project(api: Api, workspace_id: str) -> str:
    boot = api.json("GET", "/api/bootstrap")
    for p in boot.get("projects", []):
        if (p.get("workspace_id") == workspace_id) and (p.get("name") or "").strip().lower() == "m4trix":
            return p["id"]
    created = api.json("POST", "/api/projects", json_body={"workspace_id": workspace_id, "name": "m4trix", "description": "QA bug reports"})
    return created["id"]


def create_bug_task(api: Api, *, workspace_id: str, project_id: str, run_id: str, bug: Bug) -> str:
    desc = (
        f"Run id: `{run_id}`\n\n"
        f"Steps to reproduce:\n{bug.steps}\n\n"
        f"Expected:\n{bug.expected}\n\n"
        f"Actual:\n{bug.actual}\n"
    )
    if bug.evidence:
        desc += f"\nEvidence:\n{bug.evidence}\n"
    created = api.json(
        "POST",
        "/api/tasks",
        json_body={
            "workspace_id": workspace_id,
            "project_id": project_id,
            "title": f"BUG: {bug.title}",
            "description": desc,
            "priority": "High",
            "labels": ["bug", "qa", run_id],
        },
    )
    return created["id"]


def _poll(fn, *, timeout_s: float = 12.0, interval_s: float = 0.5) -> Any:
    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        last = fn()
        if last is not None:
            return last
        time.sleep(interval_s)
    return last


def main() -> int:
    run_id = f"qa-chat-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    bugs: list[Bug] = []
    api = Api()
    try:
        boot = api.json("GET", "/api/bootstrap")
        ws = (boot.get("workspaces") or [{}])[0].get("id")
        if not ws:
            raise SystemExit("bootstrap returned no workspace id; cannot continue")
        m4 = ensure_m4trix_project(api, ws)

        # Create some concrete artifacts we can target by q.
        t1 = api.json("POST", "/api/tasks", json_body={"workspace_id": ws, "project_id": m4, "title": f"QA CHAT task A {run_id}", "labels": ["qa"]})
        t2 = api.json("POST", "/api/tasks", json_body={"workspace_id": ws, "project_id": m4, "title": f"QA CHAT task B {run_id}", "labels": ["qa"]})
        n1 = api.json("POST", "/api/notes", json_body={"workspace_id": ws, "project_id": m4, "title": f"QA CHAT note A {run_id}", "body": "note a", "tags": ["qa"]})
        n2 = api.json("POST", "/api/notes", json_body={"workspace_id": ws, "project_id": m4, "title": f"QA CHAT note B {run_id}", "body": "note b", "tags": ["qa"]})

        # Agent chat should be able to create a task.
        try:
            r = api.req(
                "POST",
                "/api/agents/chat",
                json_body={
                    "workspace_id": ws,
                    "project_id": m4,
                    "instruction": f'Create a task in project "m4trix" titled "Agent created task {run_id}" with description "created by agent chat".',
                    "history": [],
                    "session_id": run_id,
                },
            )
            if r.status_code != 200:
                raise RuntimeError(f"status={r.status_code} body={r.text[:500]}")
            data = r.json()
            if not data.get("ok", False):
                raise RuntimeError(f"ok=false response: {data!r}")

            def _find():
                page = api.json("GET", "/api/tasks", params={"workspace_id": ws, "q": f"Agent created task {run_id}", "limit": 5})
                items = page.get("items") or []
                return items[0] if items else None

            found = _poll(_find, timeout_s=20.0, interval_s=0.5)
            if not found:
                raise RuntimeError("Task not found after agent chat create.")
        except Exception as exc:
            bugs.append(
                Bug(
                    title="Agent chat cannot create a task reliably",
                    steps="1. POST /api/agents/chat asking it to create a task in project m4trix\n2. Search tasks by title",
                    expected="Chat returns ok:true and task is created",
                    actual=repr(exc),
                )
            )

        # Agent chat should be able to create a note.
        try:
            r = api.req(
                "POST",
                "/api/agents/chat",
                json_body={
                    "workspace_id": ws,
                    "project_id": m4,
                    "instruction": f'Create a note in project "m4trix" titled "Agent created note {run_id}" with body "# Hello\\n\\nCreated by chat." and tags ["qa","agent"].',
                    "history": [],
                    "session_id": run_id,
                },
            )
            if r.status_code != 200:
                raise RuntimeError(f"status={r.status_code} body={r.text[:500]}")
            data = r.json()
            if not data.get("ok", False):
                raise RuntimeError(f"ok=false response: {data!r}")

            def _find():
                page = api.json("GET", "/api/notes", params={"workspace_id": ws, "q": f"Agent created note {run_id}", "limit": 5})
                items = page.get("items") or []
                return items[0] if items else None

            found = _poll(_find, timeout_s=20.0, interval_s=0.5)
            if not found:
                raise RuntimeError("Note not found after agent chat create.")
        except Exception as exc:
            bugs.append(
                Bug(
                    title="Agent chat cannot create a note reliably",
                    steps="1. POST /api/agents/chat asking it to create a note in project m4trix\n2. Search notes by title",
                    expected="Chat returns ok:true and note is created",
                    actual=repr(exc),
                )
            )

        # Agent chat: archive all tasks by q (should not archive BUG tasks).
        try:
            r = api.req(
                "POST",
                "/api/agents/chat",
                json_body={
                    "workspace_id": ws,
                    "project_id": m4,
                    "instruction": f'Archive all tasks that contain "{run_id}" in the title.',
                    "history": [],
                    "session_id": run_id,
                },
            )
            if r.status_code != 200:
                raise RuntimeError(f"status={r.status_code} body={r.text[:500]}")
            data = r.json()
            if not data.get("ok", False):
                raise RuntimeError(f"ok=false response: {data!r}")

            def _remaining():
                page = api.json("GET", "/api/tasks", params={"workspace_id": ws, "q": run_id, "archived": False, "limit": 50})
                items = page.get("items") or []
                # Only count tasks from this run (exclude BUGs, which should be separate).
                items = [t for t in items if run_id in (t.get("title") or "")]
                return len(items)

            rem = _poll(lambda: 0 if _remaining() == 0 else None, timeout_s=20.0, interval_s=0.5)
            if rem is None:
                raise RuntimeError("Some tasks still unarchived after chat archive request.")
        except Exception as exc:
            bugs.append(
                Bug(
                    title="Agent chat cannot archive tasks by query",
                    steps="1. Create tasks with unique run_id in title\n2. POST /api/agents/chat: Archive all tasks containing run_id\n3. List tasks with q=run_id and archived=false",
                    expected="All matching tasks become archived",
                    actual=repr(exc),
                )
            )

        # Agent chat: archive all notes by q.
        try:
            r = api.req(
                "POST",
                "/api/agents/chat",
                json_body={
                    "workspace_id": ws,
                    "project_id": m4,
                    "instruction": f'Archive all notes that contain "{run_id}" in the title.',
                    "history": [],
                    "session_id": run_id,
                },
            )
            if r.status_code != 200:
                raise RuntimeError(f"status={r.status_code} body={r.text[:500]}")
            data = r.json()
            if not data.get("ok", False):
                raise RuntimeError(f"ok=false response: {data!r}")

            def _remaining():
                page = api.json("GET", "/api/notes", params={"workspace_id": ws, "q": run_id, "archived": False, "limit": 50})
                items = page.get("items") or []
                items = [n for n in items if run_id in (n.get("title") or "")]
                return len(items)

            rem = _poll(lambda: 0 if _remaining() == 0 else None, timeout_s=20.0, interval_s=0.5)
            if rem is None:
                raise RuntimeError("Some notes still unarchived after chat archive request.")
        except Exception as exc:
            bugs.append(
                Bug(
                    title="Agent chat cannot archive notes by query",
                    steps="1. Create notes with unique run_id in title\n2. POST /api/agents/chat: Archive all notes containing run_id\n3. List notes with q=run_id and archived=false",
                    expected="All matching notes become archived",
                    actual=repr(exc),
                )
            )

        # Archive test artifacts via direct API in case agent didn't.
        try:
            api.json("POST", f"/api/tasks/{t1['id']}/archive", json_body={})
            api.json("POST", f"/api/tasks/{t2['id']}/archive", json_body={})
            api.json("POST", f"/api/notes/{n1['id']}/archive", json_body={})
            api.json("POST", f"/api/notes/{n2['id']}/archive", json_body={})
        except Exception:
            pass

        created_bug_ids: list[str] = []
        for bug in bugs:
            try:
                created_bug_ids.append(create_bug_task(api, workspace_id=ws, project_id=m4, run_id=run_id, bug=bug))
            except Exception as exc:
                print(f"FAILED to file bug task: {bug.title} err={exc!r}")

        print(f"QA agent-chat run_id={run_id} bugs={len(bugs)} filed={len(created_bug_ids)}")
        if created_bug_ids:
            print("Bug task ids:", created_bug_ids)
        return 0
    finally:
        api.close()


if __name__ == "__main__":
    raise SystemExit(main())
