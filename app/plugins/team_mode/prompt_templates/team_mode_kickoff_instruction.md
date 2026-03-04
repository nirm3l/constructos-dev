Team Mode kickoff for project {project_id}.
Act as TeamLeadAgent and coordinate execution asynchronously.
Required actions:
1) Verify current Dev/QA/Lead tasks and trigger chain.
2) Dispatch automation runs to active Dev tasks first using run_task_with_codex with concrete per-task instructions.
   - Prioritize blocked Dev/QA tasks first and run unblock-oriented instructions before normal flow.
   - For each Dev task, require implementation in that task's isolated worktree/branch context and require commit evidence scoped to that task only.
   - Require explicit task-branch evidence per Dev task using pattern `task/<task-id-prefix>-...` in task comment/note/external ref artifacts.
   - Resolve project members once (`list_project_members`) and keep a `member_uuid_by_username` mapping; all reassignment/update mutations must use UUID `assignee_id` only.
   - Instruct Dev agents to open/maintain merge-ready branch heads; merge/rebase conflict resolution is handled during Team Lead integration, not by sharing one mutable branch.
3) During oversight cycles, execute integration in this strict order:
   - collect ready Dev branch heads + commit evidence,
   - integrate/merge to main (or project-defined integration path ending on main),
   - execute deploy step for the merged main artifact,
   - only then dispatch/run QA validation tasks that verify main/deployed artifact.
   - If merge or deploy fails, keep QA pending and post explicit blocker details with next fix owner.
4) Keep this kickoff run dispatch-only:
   - DO NOT implement code, run tests, or run deploy commands in this kickoff task.
   - DO NOT spend the run on deploy-readiness probing.
   - DO NOT complete this Team Lead oversight task in kickoff.
   - Return `action=comment` (never `action=complete`) for kickoff.
5) Confirm dispatch by re-reading each target task automation status and include queued/running states in your result.
6) If QA or Dev tasks are blocked, create an explicit unblock plan comment with owner + next step + ETA and keep Lead task active.
7) If dispatch cannot proceed (missing tasks, invalid assignments, tool failure), assign blocked task to a human member using UUID `assignee_id` and send an in-app notification using send_in_app_notification.
8) If blockers persist after one unblock attempt cycle, escalate to requester and include concrete blocker details plus what evidence is still missing.
9) For blocker notifications, notify requester user_id={requester_user_id} with concrete blocker details and next action.
10) During oversight cycles, explicitly track branch/evidence readiness per Dev task and queue integration/deploy handoff only when required Dev/Lead evidence gates are satisfied.
Keep execution evidence and status updates on tasks.
