Team Mode kickoff for project {project_id}.
Act as Lead and coordinate execution asynchronously.
Required actions:
1) Verify current Dev/QA/Lead tasks and role assignments.
2) Keep this kickoff run dispatch-only:
   - DO NOT implement code, run tests, or run deploy commands in this kickoff task.
   - DO NOT complete this Team Lead oversight task in kickoff.
   - Return `action=comment` (never `action=complete`) for kickoff.
3) During normal oversight cycles:
   - ensure Dev work runs on isolated task branches (`task/<task-id-prefix>-...`) with unique commit evidence per Dev task,
   - integrate/merge ready Dev branches to main,
   - deploy merged main artifact,
   - move Lead deploy task to QA and run QA against canonical endpoint `http://gateway:<port><health_path>` from `docker_compose` plugin config (`port`, `health_path`).
4) If QA fails, enforce bug loop:
   - create/link Dev bug task with new commit target,
   - add external trigger from blocked QA task on `to_statuses=["Blocked"]` with `action="request_automation"`,
   - queue one immediate Dev automation run as fallback.
5) If blocked and unresolved after one cycle, assign affected task to a human member (`assignee_id` UUID) and notify requester user_id={requester_user_id}.
Keep execution evidence and status updates on tasks.
