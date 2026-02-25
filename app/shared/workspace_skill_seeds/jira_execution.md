---
skill_key: jira_execution
name: Jira Execution Skill
summary: Use this skill to mirror app task execution into Jira and keep statuses synchronized.
source_locator: seed://workspace-skills/jira-execution
mode: advisory
trust_level: verified
---
# Jira Execution Skill

Use this skill when the specification defines that Jira should track task execution.

## Workflow
- Check whether the specification, project description, or project rules define a Jira project key for tracking.
- If Jira tracking is defined, create one Jira snapshot issue per app task.
- Add each Jira issue link/key as an external reference on the matching app task.
- Keep Jira task status aligned with the app task status as work moves across board columns.
- Add a project-level external reference to the Jira project.

## Guardrails
- Do not create Jira snapshots when Jira tracking is not defined for the project.
- Keep task titles and status intent consistent between the app and Jira.
