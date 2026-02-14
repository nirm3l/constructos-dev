#!/usr/bin/env python3
"""
Exploratory QA suite (API-level) that files any detected issues as BUG tasks
in the `m4trix` project.

Run inside the container:
  docker compose exec -T task-app python scripts/qa_explore_full.py
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx


DEFAULT_USER_ID = "00000000-0000-0000-0000-000000000001"
BASE_URL = os.getenv("QA_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


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
        self.c = httpx.Client(timeout=40.0, headers={"X-User-Id": DEFAULT_USER_ID})

    def close(self) -> None:
        self.c.close()

    def req(self, method: str, path: str, *, params: dict[str, Any] | None = None, json_body: Any | None = None) -> httpx.Response:
        return self.c.request(method, BASE_URL + path, params=params, json=json_body)

    def json(self, method: str, path: str, *, params: dict[str, Any] | None = None, json_body: Any | None = None) -> Any:
        r = self.req(method, path, params=params, json_body=json_body)
        r.raise_for_status()
        return r.json()


def _truncate(s: str, n: int = 1200) -> str:
    s = s or ""
    return s if len(s) <= n else s[: n - 3] + "..."


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


def _poll_until(fn, *, timeout_s: float = 12.0, interval_s: float = 0.5) -> Any:
    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        last = fn()
        if last:
            return last
        time.sleep(interval_s)
    return last


def main() -> int:
    run_id = f"qa-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    bugs: list[Bug] = []
    api = Api()
    try:
        # Bootstrap
        boot = api.json("GET", "/api/bootstrap")
        ws = (boot.get("workspaces") or [{}])[0].get("id")
        if not ws:
            raise SystemExit("bootstrap returned no workspace id; cannot continue")
        m4 = ensure_m4trix_project(api, ws)

        # User preferences patch persists
        try:
            api.json("PATCH", "/api/me/preferences", json_body={"theme": "light", "timezone": "UTC"})
            boot2 = api.json("GET", "/api/bootstrap")
            me = boot2.get("current_user") or {}
            if me.get("timezone") != "UTC":
                raise RuntimeError(f"timezone did not persist: {me.get('timezone')!r}")
        except Exception as exc:
            bugs.append(
                Bug(
                    title="User preferences patch does not persist",
                    steps="1. PATCH /api/me/preferences {timezone: UTC}\n2. GET /api/bootstrap",
                    expected="bootstrap.current_user.timezone == UTC",
                    actual=repr(exc),
                )
            )

        # Notifications: list + mark read
        try:
            items = api.json("GET", "/api/notifications")
            if not isinstance(items, list):
                raise RuntimeError(f"Expected list, got {type(items).__name__}")
            if items:
                nid = items[0]["id"]
                api.json("POST", f"/api/notifications/{nid}/read")
                items2 = api.json("GET", "/api/notifications")
                marked = [n for n in items2 if n.get("id") == nid]
                if marked and marked[0].get("is_read") is not True:
                    raise RuntimeError("Notification did not become read after mark_read.")
        except Exception as exc:
            bugs.append(
                Bug(
                    title="Notifications list/mark-read broken",
                    steps="1. GET /api/notifications\n2. POST /api/notifications/{id}/read\n3. GET /api/notifications",
                    expected="Status 200; notification toggles to is_read:true",
                    actual=repr(exc),
                )
            )

        # Notifications SSE: should at least emit ping quickly
        try:
            with api.c.stream("GET", BASE_URL + "/api/notifications/stream", params={"workspace_id": ws}, timeout=10.0) as r:
                if r.status_code != 200:
                    raise RuntimeError(f"status={r.status_code} body={_truncate(r.text)}")
                buf = ""
                got_ping = False
                start = time.time()
                for chunk in r.iter_text():
                    buf += chunk
                    if "event: ping" in buf:
                        got_ping = True
                        break
                    if time.time() - start > 6:
                        break
                if not got_ping:
                    raise RuntimeError(f"Did not see ping event. partial={_truncate(buf, 800)!r}")
        except Exception as exc:
            bugs.append(
                Bug(
                    title="Notifications SSE stream does not emit ping",
                    steps="1. Connect to GET /api/notifications/stream?workspace_id=<ws>\n2. Wait up to ~6s",
                    expected='Receive at least one SSE "ping" event',
                    actual=repr(exc),
                )
            )

        # Saved views are tested separately: there is a known crash-on-projection issue in
        # EventStore mode when an event is projected more than once.

        # Projects: create with custom statuses + board + activity + delete moves tasks to inbox
        project_id = ""
        task_ids: list[str] = []
        try:
            project = api.json(
                "POST",
                "/api/projects",
                json_body={
                    "workspace_id": ws,
                    "name": f"QA Project {run_id}",
                    "description": "QA project for board/activity/delete tests",
                    "custom_statuses": ["Todo", "Doing", "Blocked", "Done"],
                },
            )
            project_id = project["id"]
            # Create tasks in each lane
            for st in ["Todo", "Doing", "Blocked", "Done"]:
                t = api.json(
                    "POST",
                    "/api/tasks",
                    json_body={
                        "workspace_id": ws,
                        "project_id": project_id,
                        "title": f"QA lane {st} {run_id}",
                        "description": f"status {st}",
                        "priority": "Low",
                        "labels": ["qa", "board"],
                    },
                )
                task_ids.append(t["id"])
                # set status if not default
                if st != "Todo":
                    api.json("PATCH", f"/api/tasks/{t['id']}", json_body={"status": st})
            board = api.json("GET", f"/api/projects/{project_id}/board")
            statuses = board.get("statuses") or []
            if statuses != ["Todo", "Doing", "Blocked", "Done"]:
                raise RuntimeError(f"Board statuses mismatch: {statuses!r}")
            lanes = board.get("lanes") or {}
            if not all(lanes.get(s) for s in ["Todo", "Doing", "Blocked", "Done"]):
                raise RuntimeError(f"Expected non-empty lanes for all statuses. lanes_keys={list(lanes.keys())!r}")
            activity = api.json("GET", f"/api/projects/{project_id}/activity")
            if not isinstance(activity, list):
                raise RuntimeError("Project activity is not a list.")

            # Delete project, ensure tasks moved to inbox (project_id None)
            api.json("DELETE", f"/api/projects/{project_id}")
            moved = api.json("GET", "/api/tasks", params={"workspace_id": ws, "q": f"QA lane", "limit": 50})
            items = moved.get("items") if isinstance(moved, dict) else moved
            moved_rows = [x for x in (items or []) if run_id in (x.get("title") or "")]
            if not moved_rows:
                raise RuntimeError("Did not find moved tasks after project delete.")
            still_in_project = [x for x in moved_rows if x.get("project_id") == project_id]
            if still_in_project:
                raise RuntimeError(f"Some tasks still reference deleted project. count={len(still_in_project)}")
        except Exception as exc:
            bugs.append(
                Bug(
                    title="Project board/activity/delete workflow broken",
                    steps="1. Create project with custom statuses\n2. Create tasks; patch statuses\n3. GET /projects/{id}/board and /activity\n4. DELETE project\n5. Verify tasks moved to inbox",
                    expected="Board shows correct lanes; delete moves tasks to inbox (project_id becomes null)",
                    actual=repr(exc),
                )
            )

        # Tasks: bulk actions, reorder, calendar, export
        try:
            # Create a few tasks to reorder and bulk-complete/archive
            t1 = api.json("POST", "/api/tasks", json_body={"workspace_id": ws, "project_id": m4, "title": f"QA bulk 1 {run_id}", "labels": ["qa"]})
            t2 = api.json("POST", "/api/tasks", json_body={"workspace_id": ws, "project_id": m4, "title": f"QA bulk 2 {run_id}", "labels": ["qa"]})
            t3 = api.json("POST", "/api/tasks", json_body={"workspace_id": ws, "project_id": m4, "title": f"QA bulk 3 {run_id}", "labels": ["qa"]})
            ids = [t1["id"], t2["id"], t3["id"]]

            api.json("POST", "/api/tasks/bulk", json_body={"task_ids": ids, "action": "complete", "payload": {}})
            done = api.json("GET", "/api/tasks", params={"workspace_id": ws, "q": f"QA bulk", "limit": 50})
            items = done.get("items") if isinstance(done, dict) else done
            rows = [x for x in (items or []) if run_id in (x.get("title") or "")]
            if not rows:
                raise RuntimeError("Bulk tasks not found in list.")
            if any((x.get("status") != "Done") for x in rows):
                raise RuntimeError("Some tasks not completed after bulk complete.")

            # Reopen + archive via bulk
            api.json("POST", "/api/tasks/bulk", json_body={"task_ids": ids, "action": "reopen", "payload": {"status": "To do"}})
            api.json("POST", "/api/tasks/bulk", json_body={"task_ids": ids, "action": "archive", "payload": {}})

            arch = api.json("GET", "/api/tasks", params={"workspace_id": ws, "q": f"QA bulk", "archived": True, "limit": 50})
            aitems = arch.get("items") if isinstance(arch, dict) else arch
            if len(aitems or []) < 3:
                raise RuntimeError(f"Expected 3 archived tasks, got {len(aitems or [])}")

            # Reorder should not error
            api.json("POST", "/api/tasks/reorder", params={"workspace_id": ws}, json_body={"ordered_ids": ids, "status": None})

            # Calendar and export endpoints
            from_d = date.today()
            to_d = from_d + timedelta(days=7)
            api.json("GET", "/api/calendar", params={"workspace_id": ws, "from_date": str(from_d), "to_date": str(to_d)})
            # Export returns a Response; just validate 200.
            r = api.req("GET", "/api/export", params={"workspace_id": ws, "format": "json"})
            if r.status_code != 200:
                raise RuntimeError(f"/api/export status={r.status_code} body={_truncate(r.text)}")
        except Exception as exc:
            bugs.append(
                Bug(
                    title="Tasks bulk/reorder/calendar/export broken",
                    steps="1. Create 3 tasks\n2. POST /api/tasks/bulk complete/reopen/archive\n3. POST /api/tasks/reorder\n4. GET /api/calendar\n5. GET /api/export",
                    expected="All endpoints succeed and state changes reflect in list",
                    actual=repr(exc),
                )
            )

        # Task: watch toggle + activity present
        try:
            t = api.json("POST", "/api/tasks", json_body={"workspace_id": ws, "project_id": m4, "title": f"QA watch {run_id}"})
            tid = t["id"]
            w1 = api.json("POST", f"/api/tasks/{tid}/watch", json_body={})
            if "watched" not in w1:
                raise RuntimeError(f"Unexpected watch response: {w1!r}")
            w2 = api.json("POST", f"/api/tasks/{tid}/watch", json_body={})
            if w2.get("watched") == w1.get("watched"):
                raise RuntimeError("Watch toggle did not toggle.")
            logs = api.json("GET", f"/api/tasks/{tid}/activity")
            if not isinstance(logs, list):
                raise RuntimeError("Task activity not a list.")
        except Exception as exc:
            bugs.append(
                Bug(
                    title="Task watch/activity broken",
                    steps="1. Create task\n2. POST /tasks/{id}/watch twice\n3. GET /tasks/{id}/activity",
                    expected="watched toggles, activity returns list",
                    actual=repr(exc),
                )
            )

        # Task automation: request run + status endpoint returns something reasonable
        try:
            t = api.json("POST", "/api/tasks", json_body={"workspace_id": ws, "project_id": m4, "title": f"QA automation {run_id}"})
            tid = t["id"]
            api.json("POST", f"/api/tasks/{tid}/automation/run", json_body={"instruction": "Reply with a short summary of this task."})
            # Status should be reachable, even if it remains queued for a while.
            st = api.json("GET", f"/api/tasks/{tid}/automation")
            if not isinstance(st, dict):
                raise RuntimeError("Automation status is not an object.")
        except Exception as exc:
            bugs.append(
                Bug(
                    title="Task automation request/status broken",
                    steps="1. Create task\n2. POST /tasks/{id}/automation/run\n3. GET /tasks/{id}/automation",
                    expected="Request returns ok:true and status endpoint returns object",
                    actual=repr(exc),
                )
            )

        # Scheduling: scheduled task should queue and runner should advance schedule_state; recurring should re-arm.
        try:
            fire_at = datetime.now(timezone.utc) + timedelta(seconds=6)
            t = api.json(
                "POST",
                "/api/tasks",
                json_body={
                    "workspace_id": ws,
                    "project_id": m4,
                    "title": f"QA schedule {run_id}",
                    "task_type": "scheduled_instruction",
                    "scheduled_instruction": "echo hello from schedule",
                    "scheduled_at_utc": _iso(fire_at),
                    "schedule_timezone": "UTC",
                    "recurring_rule": "every:1m",
                },
            )
            tid = t["id"]

            def _done_or_failed():
                row = api.json("GET", "/api/tasks", params={"workspace_id": ws, "q": f"QA schedule {run_id}", "limit": 5})
                items = row.get("items") if isinstance(row, dict) else row
                if not items:
                    return None
                s = items[0].get("schedule_state")
                # "done" or "failed" indicates execution finished.
                return items[0] if s in {"done", "failed"} else None

            finished = _poll_until(_done_or_failed, timeout_s=30.0, interval_s=1.0)
            if not finished:
                raise RuntimeError("Scheduled task did not reach done/failed within 30s.")

            # Recurring should re-arm back to idle with a future scheduled_at_utc.
            def _rearmed():
                row = api.json("GET", "/api/tasks", params={"workspace_id": ws, "q": f"QA schedule {run_id}", "limit": 5})
                items = row.get("items") if isinstance(row, dict) else row
                if not items:
                    return None
                it = items[0]
                if it.get("recurring_rule") != "every:1m":
                    return None
                if it.get("schedule_state") != "idle":
                    return None
                sat = it.get("scheduled_at_utc")
                return it if sat else None

            rearmed = _poll_until(_rearmed, timeout_s=20.0, interval_s=1.0)
            if not rearmed:
                raise RuntimeError("Recurring scheduled task did not re-arm to idle with scheduled_at_utc.")
        except Exception as exc:
            bugs.append(
                Bug(
                    title="Scheduled/recurring tasks do not execute and re-arm",
                    steps="1. Create scheduled_instruction task scheduled a few seconds ahead with recurring_rule every:1m\n2. Poll /api/tasks for schedule_state done/failed\n3. Poll for re-armed idle state with next scheduled_at_utc",
                    expected="Task executes and then re-arms for next run",
                    actual=repr(exc),
                )
            )

        # Notes: patch/pin/unpin/delete filters
        try:
            n = api.json(
                "POST",
                "/api/notes",
                json_body={"workspace_id": ws, "project_id": m4, "title": f"QA note lifecycle {run_id}", "body": "hello", "tags": ["qa"]},
            )
            nid = n["id"]
            api.json("PATCH", f"/api/notes/{nid}", json_body={"tags": ["qa", "updated"], "body": "updated"})
            api.json("POST", f"/api/notes/{nid}/pin", json_body={})
            pinned = api.json("GET", "/api/notes", params={"workspace_id": ws, "pinned": True, "q": run_id, "limit": 10})
            items = pinned.get("items") if isinstance(pinned, dict) else pinned
            if not any(x.get("id") == nid for x in (items or [])):
                raise RuntimeError("Pinned note not returned with pinned=true filter.")
            api.json("POST", f"/api/notes/{nid}/unpin", json_body={})
            api.json("POST", f"/api/notes/{nid}/delete", json_body={})
            alive = api.json("GET", "/api/notes", params={"workspace_id": ws, "q": run_id, "limit": 10})
            aitems = alive.get("items") if isinstance(alive, dict) else alive
            if any(x.get("id") == nid for x in (aitems or [])):
                raise RuntimeError("Deleted note still visible in list.")
        except Exception as exc:
            bugs.append(
                Bug(
                    title="Notes lifecycle endpoints broken",
                    steps="1. Create note\n2. PATCH note tags/body\n3. PIN then list pinned\n4. UNPIN\n5. DELETE then list",
                    expected="Pinned filter works and deleted note disappears from list",
                    actual=repr(exc),
                )
            )

        # Agents chat: basic response contract ok + no 500
        try:
            r = api.req(
                "POST",
                "/api/agents/chat",
                json_body={"workspace_id": ws, "project_id": m4, "instruction": "List the projects in this workspace.", "history": [], "session_id": run_id},
            )
            if r.status_code != 200:
                raise RuntimeError(f"status={r.status_code} body={_truncate(r.text)}")
            data = r.json()
            if "ok" not in data:
                raise RuntimeError(f"Missing ok in response: {data!r}")
        except Exception as exc:
            bugs.append(
                Bug(
                    title="Agent chat endpoint fails or returns invalid payload",
                    steps="1. POST /api/agents/chat with a simple instruction",
                    expected="200 OK with JSON containing ok/action/summary/comment fields",
                    actual=repr(exc),
                )
            )

        # Debug endpoints: metrics should be reachable
        try:
            m = api.req("GET", "/api/metrics")
            if m.status_code != 200:
                raise RuntimeError(f"status={m.status_code} body={_truncate(m.text)}")
        except Exception as exc:
            bugs.append(
                Bug(
                    title="Debug metrics endpoint fails",
                    steps="1. GET /api/metrics",
                    expected="200 OK",
                    actual=repr(exc),
                )
            )

        # Backend error messages English sanity (deliberate validation error)
        try:
            r = api.req("POST", "/api/tasks", json_body={"workspace_id": ws, "title": "x", "task_type": "bad_type"})
            if r.status_code != 422:
                raise RuntimeError(f"Expected 422, got {r.status_code} body={_truncate(r.text)}")
            # Ensure error is not localized (very rough check).
            if any(w in r.text.lower() for w in ["gres", "ne moze", "nije", "uspjes"]):
                raise RuntimeError(f"Looks localized: {r.text}")
        except Exception as exc:
            bugs.append(
                Bug(
                    title="Backend validation errors not in English",
                    steps="1. POST /api/tasks with invalid task_type\n2. Inspect error message",
                    expected="422 with English error text",
                    actual=repr(exc),
                )
            )

        created_bug_ids: list[str] = []
        for bug in bugs:
            try:
                created_bug_ids.append(create_bug_task(api, workspace_id=ws, project_id=m4, run_id=run_id, bug=bug))
            except Exception as exc:
                # Last resort: print to stderr so it shows up in container logs.
                print(f"FAILED to file bug task: {bug.title} err={exc!r}", file=sys.stderr)

        print(f"QA run_id={run_id} bugs={len(bugs)} filed={len(created_bug_ids)}")
        if created_bug_ids:
            print("Bug task ids:", created_bug_ids)
        return 0
    finally:
        api.close()


if __name__ == "__main__":
    raise SystemExit(main())
