---
skill_key: github_delivery
name: GitHub Delivery Skill
summary: Use this skill for GitHub-backed task delivery, commit traceability, and optional PR workflows.
source_locator: seed://workspace-skills/github-delivery
mode: advisory
trust_level: verified
---
# GitHub Delivery Skill

Use this skill when a project must be implemented and published through GitHub.

## Source Of Truth
- Read implementation requirements from project specifications first.
- If needed, also apply project description and project rules.
- Use only the repository and branching policy defined there.

## Implementation Workflow
- When asked to implement the project, create the project structure on disk as defined by the project specification (for example `/<project-name>`).
- Use GitHub MCP for repository operations and publishing to the repository defined in the specification.
- Implement work task by task.
- For each implemented task, create a commit and add the commit ID as an external reference on that task.
- Add a project-level external reference to the GitHub repository.
- As task implementation progresses, move tasks across the board columns according to project workflow.

## Pull Request Decision Rules
- If specifications, project description, or project rules require pull requests per task: create PRs per task.
- If approvals are required: wait for approval and assign the task to a human team member while waiting.
- If pull requests are required but approval wait is not required: merge automatically after checks and add the PR link as an external reference.
- If pull requests are not required: commit directly to `main`, add the commit as an external reference on the task, and move the task to `Done` (or the equivalent final column defined by the project).
