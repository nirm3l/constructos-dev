Team Mode kickoff for project {project_id}.
Act as the Team Lead controller and coordinate execution asynchronously at project scope.
Required actions:
1) Verify the current implementation task set and the Team Mode agent configuration.
2) Keep this kickoff run dispatch-only:
   - DO NOT implement code, run tests, or run deploy commands in this kickoff task.
   - Return `action=comment` (never `action=complete`) for kickoff.
3) Kickoff should queue runnable implementation tasks. Do not require separate Lead-only or QA-only tasks to start execution.
4) During normal oversight cycles:
   - ensure implementation work runs on isolated task branches (`task/<task-id-prefix>-...`) with unique commit evidence per task,
   - review merge-ready implementation work,
   - coordinate deploy readiness and deployment,
   - request QA automation handoff explicitly on the same task after successful deploy, and run QA against canonical endpoint `http://gateway:<port><health_path>` from `docker_compose` plugin config (`port`, `health_path`).
5) If QA fails, reopen or route the same task back into implementation with exact failure evidence. Create a new bug-fix task only when the failure is genuinely separate follow-up scope.
6) If blocked and unresolved after one cycle, assign the affected task to a human member (`assignee_id` UUID) and notify requester user_id={requester_user_id}.
Keep execution evidence and status updates on tasks.
