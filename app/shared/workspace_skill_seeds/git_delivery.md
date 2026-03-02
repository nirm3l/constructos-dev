---
skill_key: git_delivery
name: Git Delivery Skill
summary: Use this skill for repository-based implementation workflow, branch/commit policy, and delivery evidence independent of provider.
source_locator: seed://workspace-skills/git-delivery
mode: enforced
trust_level: verified
---
# Git Delivery Skill

Use this skill whenever implementation is expected to run against a Git repository.

## Repository Preconditions
- Validate repository presence before implementation (`.git` exists and working tree is accessible).
- If repository is missing, set execution to `Blocked` with a concrete prerequisite note.

## Branching And Commits
- Developers implement on feature branches named `task/<task-id>-<slug>`.
- Each Dev task requires at least one commit before handoff.
- Keep commits scoped to task intent and include task id in commit message.

## Evidence Contract
- Internal implementation evidence must be linked through task notes.
- `external_refs` should prefer real external URLs (for example Git remote links, CI links, review links).
- If remote URL is unavailable, store local commit hash evidence in a linked task note and task comment, and add a commit reference in `external_refs` (for example `commit:<sha>`).
- QA must have verifiable artifacts (test logs, reports, traces, or equivalent evidence) before final acceptance.

## Handoff Rules
- Dev task cannot move beyond `QA` without commit evidence.
- QA must verify reproducible artifacts (test output, logs, or commit trace) before final acceptance.
