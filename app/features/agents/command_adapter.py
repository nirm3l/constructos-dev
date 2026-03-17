from __future__ import annotations

import json
import sys


def _is_completed_status(status: str | None) -> bool:
    normalized = str(status or "").strip().lower()
    return normalized in {"done", "completed"}


def main() -> int:
    raw = sys.stdin.read().strip()
    if not raw:
        print(json.dumps({"action": "comment", "summary": "No input context.", "comment": "No task context received."}))
        return 0

    ctx = json.loads(raw)
    instruction = str(ctx.get("instruction") or "")
    status = str(ctx.get("status") or "To Do")

    should_complete = bool(ctx.get("task_completion_requested"))
    if should_complete and not _is_completed_status(status):
        print(json.dumps({"action": "complete", "summary": "Command adapter marked task as completed."}))
        return 0

    comment = "Command adapter executed task automation request."
    if instruction:
        comment += f"\nInstruction: {ctx.get('instruction')}"
    print(json.dumps({"action": "comment", "summary": "Command adapter left a task comment.", "comment": comment}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
