Team Mode kickoff for project {project_id}.
Act as TeamLeadAgent and coordinate execution asynchronously.
Required actions:
1) Verify current Dev/QA/Lead tasks and trigger chain.
2) Dispatch automation runs to active Dev and QA tasks using run_task_with_codex with concrete per-task instructions.
   - Prioritize blocked tasks first (Dev/QA in `Blocked`) and run unblock-oriented instructions before normal flow.
3) Keep this kickoff run dispatch-only:
   - DO NOT implement code, run tests, or run deploy commands in this kickoff task.
   - DO NOT spend the run on deploy-readiness probing.
   - DO NOT complete this Team Lead oversight task in kickoff.
   - Return `action=comment` (never `action=complete`) for kickoff.
4) Confirm dispatch by re-reading each target task automation status and include queued/running states in your result.
5) If QA or Dev tasks are blocked, create an explicit unblock plan comment with owner + next step + ETA and keep Lead task active.
6) If dispatch cannot proceed (missing tasks, invalid assignments, tool failure), assign blocked task to a human member and send an in-app notification using send_in_app_notification.
7) If blockers persist after one unblock attempt cycle, escalate to requester and include concrete blocker details plus what evidence is still missing.
8) For blocker notifications, notify requester user_id={requester_user_id} with concrete blocker details and next action.
Keep execution evidence and status updates on tasks.
