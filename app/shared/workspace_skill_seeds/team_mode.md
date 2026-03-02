---
skill_key: team_mode
name: Team Mode Skill
summary: Use this skill to run delivery with a Lead, two implementation agents, and one QA agent through task triggers and scheduled oversight.
source_locator: seed://workspace-skills/team-mode
mode: enforced
trust_level: verified
---
# Team Mode Skill

Use this skill when a project should be executed by a structured multi-agent delivery team.

## Agent Roster
- M0rph3u5 (`TeamLeadAgent`)
- Tr1n1ty (`DeveloperAgent`)
- N30 (`DeveloperAgent`)
- 0r4cl3 (`QAAgent`)

## Team Mode Activation Contract
- When Team Mode is applied, ensure all roster agents exist as `agent` users.
- Ensure all roster agents are members of the project with the expected Team Mode project roles.
- Keep assignment idempotent on repeated apply.
- When creating tasks, always use `assignee_id` as the member `user_id` UUID from project membership.
- Never use agent display names/usernames as `assignee_id` values.
- Treat Team Mode project setup as incomplete until all of the following are true:
  - Team Mode board statuses are configured (`To do`, `Dev`, `QA`, `Lead`, `Done`, `Blocked`) unless the user explicitly overrides.
  - Implementation tasks are assigned to Team Mode agents and start in `Dev`.
  - QA flow and Lead oversight automation are represented by task triggers and/or schedule.
  - A deploy task exists with Docker Compose execution instructions scoped to app services on the workspace stack project `constructos-ws-default` (or explicit user override).
  - Deployment intent is recorded as a setup artifact (for example a pinned note or deploy-task note) with target port and stack.
  - Team Lead recurring schedule triggers set `run_on_statuses` explicitly to Team Mode statuses (default `["Lead"]`).
  - Team Mode setup does not rely on generic schedule defaults such as `In progress`.
  - A project rule named `Gate Policy` exists (JSON) so required verification gates are explicit and editable in UI.

## Delivery Workflow
- Developers execute implementation through the delivery contract enforced by `git_delivery`.
- Team Mode orchestration must not bypass `git_delivery` requirements for branching, commits, and evidence.
- Move tasks across board statuses exactly as defined by the project workflow.

## Team Lead Responsibilities
- Run recurring oversight using scheduled task automation.
- Monitor blocked, failed, and stale tasks and coordinate resolution.
- Deploy the app stack using project-defined Docker Compose instructions scoped to app services.
- Default deployment stack for chat-driven delivery is `constructos-ws-default` unless the user explicitly requests a different project name.
- Record deployment execution evidence on the deploy task (for example command snippet + health URL/check output + runtime status).
- During setup-only requests, record deployment intent (`stack`, `port`, `health path`) and mark execution state as `not_started`.
- Keep `Gate Policy` updated for setup/execution mode transitions (for example runtime deploy health not required in setup-only mode, required in execution mode).
- If a blocker cannot be resolved, assign the task to a human member and move it to escalation status.

## QA Responsibilities
- Trigger QA after implementation status transitions (for example when work enters review/testing).
- Execute automated validation using project test strategy (Playwright, integration tests, smoke checks, or equivalent).
- After Team Lead deployment, run post-deploy QA checks against the deployed service endpoint.
- Report failures with reproducible steps and evidence links, then verify fixes after re-run.
- QA evidence should include explicit outcome markers (pass/fail) plus at least one concrete artifact reference or log excerpt.

## Guardrails
- Do not skip required QA verification before moving work to final done states.
- Keep app and external tracker statuses synchronized when GitHub/Jira skills are also active.
- Keep Team Mode orchestration independent from Git provider details (GitHub specifics belong to `github_delivery`).
- Keep deployment and automation actions inside project-defined operational boundaries.
- QA failure requires explicit bug/fix loop (new bug task or linked existing task, fix commit evidence, and QA re-check evidence).
- Failed post-deploy QA must move work back to Dev with a bug task, then return to Lead for re-deploy before final QA sign-off.
- Prefer explicit Team Mode trigger transitions:
  - Dev tasks self-trigger on `to_statuses=["QA"]`
  - QA task external-trigger from Dev task ids on `to_statuses=["QA"]`
  - Lead oversight external-trigger from QA task ids on `to_statuses=["Done"]`
  - Deploy external-trigger from Lead task ids on `to_statuses=["Done"]`
