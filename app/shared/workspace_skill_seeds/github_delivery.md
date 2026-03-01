---
skill_key: github_delivery
name: GitHub Delivery Skill
summary: Use this skill for GitHub-specific delivery orchestration (PR lifecycle, reviewers, labels, merge policy, issue links).
source_locator: seed://workspace-skills/github-delivery
mode: advisory
trust_level: verified
---
# GitHub Delivery Skill

Use this skill when a project uses GitHub as the delivery platform.
Core Git execution rules are enforced by `git_delivery`.

## GitHub Scope
- Manage pull request lifecycle (open/update/rebase/merge).
- Configure reviewers and review requests.
- Apply labels and maintain GitHub issue/PR linkage.
- Keep task state synchronized with GitHub state transitions when policy requires it.
- Record canonical GitHub URLs (PR, issue, workflow runs) in task external references.

## Pull Request Decision Rules
- If specifications, project description, or project rules require pull requests per task: create PRs per task.
- If approvals are required: wait for approval and assign the task to a human team member while waiting.
- If pull requests are required but approval wait is not required: merge automatically after checks and add the PR link as an external reference.
- If pull requests are not required: follow merge policy from project rules and still keep GitHub issue/label state aligned.
