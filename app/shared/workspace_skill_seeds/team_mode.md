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
  - A deploy task exists with Docker Compose execution instructions scoped to app services.
  - Team Lead recurring schedule triggers set `run_on_statuses` explicitly to Team Mode statuses (default `["Lead"]`).
  - Team Mode setup does not rely on generic schedule defaults such as `In progress`.

## Delivery Workflow
- Developers implement tasks on Git feature branches and keep branch names tied to task IDs.
- Developers add commit and pull request links as task external references.
- Developers track other team member branch changes and resolve merge conflicts before final merge.
- Move tasks across board statuses exactly as defined by the project workflow.

## Team Lead Responsibilities
- Run recurring oversight using scheduled task automation.
- Monitor blocked, failed, and stale tasks and coordinate resolution.
- Deploy the app stack using project-defined Docker Compose instructions scoped to app services.
- If a blocker cannot be resolved, assign the task to a human member and move it to escalation status.

## QA Responsibilities
- Trigger QA after implementation status transitions (for example when work enters review/testing).
- Execute automated validation using project test strategy (Playwright, integration tests, smoke checks, or equivalent).
- Report failures with reproducible steps and evidence links, then verify fixes after re-run.

## Guardrails
- Do not skip required QA verification before moving work to final done states.
- Keep app and external tracker statuses synchronized when GitHub/Jira skills are also active.
- Keep deployment and automation actions inside project-defined operational boundaries.
- Prefer explicit Team Mode trigger transitions:
  - Dev tasks self-trigger on `to_statuses=["QA"]`
  - QA task external-trigger from Dev task ids on `to_statuses=["QA"]`
  - Lead oversight external-trigger from QA task ids on `to_statuses=["Done"]`
  - Deploy external-trigger from Lead task ids on `to_statuses=["Done"]`
