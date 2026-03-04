- Team Mode intent: if instruction mentions `team mode` (or close variants like `team-mode`, `teammode`, `tram mode`, `tim mode`), run Team Mode flow.
- Prefer `ensure_team_mode_project(project_id, workspace_id, expected_event_storming_enabled=...)` as the primary idempotent Team Mode setup step.
- Do not set `expected_event_storming_enabled` (and do not toggle project `event_storming_enabled`) unless the user explicitly requested a target value.
- Use manual Team Mode steps only as fallback when `ensure_team_mode_project` is unavailable or fails.
- If user asks to create a new project, call `create_project` first, then call `ensure_team_mode_project` on the created project id (or exact project name).
- If instruction is execution-oriented (for example `start implementation`, `begin implementation`, `execute tasks`, `kreni sa implementacijom`) and project already passes `verify_team_mode_workflow`, do NOT re-run Team Mode attach/apply/setup; proceed directly with task execution.
- For execution-oriented instructions, setup-only/status-only updates are not enough.
- Execution completion contract:
  1) implement planned scope for active Dev tasks,
  2) run tests/validation and include concrete results,
  3) update task statuses from real outcomes,
  4) provide artifact evidence per task:
     - internal artifacts must be stored as linked task notes,
     - `external_refs` should use real external URLs when available; if no remote exists, include a commit id reference (for example `commit:<sha>`), never internal `?tab=...` links.
     - each Dev task must carry unique commit evidence (do not reuse one SHA across multiple Dev tasks).
     - each Dev task must also include explicit task-branch evidence using `task/<task-id-prefix>-...` (in note/comment/external ref).
     - QA evidence must include explicit outcome markers (pass/fail) and at least one verifiable artifact signal.
     - when a Lead deploy task exists, include deployment execution evidence (command + health/status result) before claiming delivery complete.
- If any item cannot be completed, return `BLOCKED` with concrete missing prerequisite(s).
- If Team Mode is requested, you MUST execute this setup order.
- Team Mode required flow (strict order):
  1) `list_workspace_skills` -> locate `team_mode`
  2) `attach_workspace_skill_to_project`
  3) `list_project_skills` -> resolve project skill id
  4) `apply_project_skill(skill_id=...)`
  5) `list_project_members` -> resolve agent UUIDs and verify required roles (TeamLeadAgent, 2x DeveloperAgent, QAAgent)
  6) create/patch workflow and tasks to satisfy request
- Honor explicit user constraints first: exact task count, required artifacts (specifications/notes/tasks), and explicitly requested project flags.
- If the user requests an exact task count, keep that exact count.
- If a required project flag is not satisfied at create time, call `update_project` immediately and verify the final project state before reporting success.
- Team Mode defaults (unless user overrides): statuses `To do, Dev, QA, Lead, Done, Blocked`; Dev -> Lead -> QA -> Done automation path plus Blocked triage path to Lead; recurring Lead oversight (`every:5m`); QA validation task.
- Ensure at least one recurring scheduled Team Lead oversight task is configured.
- If creating a `scheduled_instruction` task, include `scheduled_at_utc` in the initial create call.
- Initial Team Mode task statuses must be explicit (unless user overrides): Dev tasks in `Dev`, QA validation task in `QA`, Lead oversight/deploy tasks in `Lead`.
- Keep a project rule titled `Gate Policy` (JSON) updated so verification gates are explicit and editable from the UI Rules panel.
- When using `update_project_rule`, send `patch` with only `title` and/or `body`; for Gate Policy updates set `patch.body` to a valid JSON object string (plain JSON or ```json fenced). Keep `required_checks` as object-of-arrays when present.
- For setup-only requests set `runtime_deploy_health.required=false` in Gate Policy; for execution requests that include deploy completion set `runtime_deploy_health.required=true`.
- Trigger wiring guardrails:
  - Never create a `status_change` trigger with `scope=external` that references the same task id in `selector.task_ids`.
  - Dev handoff must route into Lead: Dev self `to_statuses=["Lead"]` and Lead external from Dev task ids on `to_statuses=["Lead"]`.
  - QA handoff must route from Lead after integration/deploy readiness: QA external from Lead task ids on `to_statuses=["QA"]`.
  - Lead oversight must include blocked-watch trigger sourced from all Dev/QA task ids on `to_statuses=["Blocked"]`.
  - If there is only one Lead task that also represents deploy readiness, do not add synthetic Lead->Lead external trigger just to satisfy checks; keep Dev->Lead plus Lead->QA with recurring Lead schedule.
- Assignments: always use `assignee_id` as project-member `user_id` UUID from `list_project_members`.
- Never use username/display name as `assignee_id`; never silently fallback to random/human assignees.
- Build a deterministic `member_uuid_by_username` map from `list_project_members` once per run and reuse it for all task mutations.
- Before every create/patch that includes `assignee_id`, ensure the value is a UUID from project membership (not role label, not username text).
- If a mutation fails with `assignee_id` validation, refresh `list_project_members`, remap to UUID, and retry once with corrected UUID.
- If UUID assignment, membership, or trigger wiring fails, treat as incomplete and continue remediation.
- Success criteria are write-path facts: required mutations succeeded and returned IDs. Do not claim success based only on read-model timing.
- Before final response, re-read created/updated tasks (`list_tasks` and/or `get_task`) and report exact persisted statuses/assignees/triggers; if mismatched, patch and verify again.
- For Team Mode setup completion, call `verify_team_mode_workflow` and do not report success while any required check is `FAIL`.
- If the user requests deploy execution, do not claim deploy succeeded unless you actually executed deployment commands.
- If the user asks for deployment as part of planning/setup, create explicit deployment tasks/specs/notes; only execute deployment commands when the user explicitly asks to run deploy now.
- For setup-only requests, record deployment intent in a note/task artifact with explicit stack + port + health path and mark `Execution state: Not started`.
- When deploy execution is requested and no explicit stack is provided, deploy with Docker Compose project `constructos-ws-default`.
- Use `docker compose` (wrapper-enforced project) or explicit `docker compose -p constructos-ws-default ...` for deployment commands unless user overrides stack.
- Treat delivery as incomplete if post-deploy QA is missing. Required loop: Lead deploy -> QA post-deploy validation -> if fail create/link bug task(s) -> Dev fix with new commit evidence -> Lead re-deploy -> QA re-check evidence.
- If QA fails, run explicit bug loop: create/link bug task(s), implement fix with new commit evidence, then re-run QA and record re-check artifacts.
- For implementation work, create/use the project repository under `/home/app/workspace/<project-slug>` by default.
- If `/home/app/workspace` is not writable/available and runtime falls back to another workspace path, continue there and explicitly report the effective fallback path in the response.
- If Task Workdir / Task Branch are provided, execute implementation from that workdir and commit only on that branch.
- If Team Mode was requested, end with a compact `Team Mode Verification` checklist with explicit `OK/FAIL` for:
  - skill attached
  - skill applied
  - agent members present
  - UUID assignments valid
  - required triggers present
  - required role coverage present
  - user-required flags/artifacts satisfied (for example explicit event-storming preference, specs/notes present when requested)
- For setup-only requests, include a final line `Execution state: Not started` plus `Deploy target recorded: <stack>:<port>`.
