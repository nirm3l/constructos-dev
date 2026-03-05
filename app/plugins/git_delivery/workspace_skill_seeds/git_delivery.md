---
skill_key: git_delivery
name: Git Delivery Skill
summary: Use this skill for repository-based implementation workflow on main, per-task commit policy, and delivery evidence independent of provider.
source_locator: seed://workspace-skills/git-delivery
mode: enforced
trust_level: verified
---
# Git Delivery Skill

Use this skill whenever implementation is expected to run against a Git repository.

## Repository Preconditions
- Validate repository presence before implementation (`.git` exists and working tree is accessible).
- If repository is missing, set execution to `Blocked` with a concrete prerequisite note.

## Main Branch And Commits
- In standalone Git Delivery mode (without Team Mode), developers implement directly on `main`.
- When Team Mode is enabled, Team Mode workflow may enforce per-task branches/worktrees.
- Each Dev task requires at least one commit before handoff.
- Each Dev task must reference a unique commit SHA (do not reuse the same commit evidence across multiple Dev tasks).
- Keep commits scoped to task intent and include task id in commit message.
- Do not close multiple Dev tasks with a single aggregate commit unless the user explicitly authorizes that exception.

## Evidence Contract
- Internal implementation evidence must be linked through task notes.
- `external_refs` should prefer real external URLs (for example Git remote links, CI links, review links).
- If remote URL is unavailable, store local commit hash evidence in a linked task note and task comment, and add a commit reference in `external_refs` (for example `commit:<sha>`).
- Commit evidence must include an actual SHA token (`[0-9a-f]{7,40}`) so automated verification can resolve it.
- QA must have verifiable artifacts (test logs, reports, traces, or equivalent evidence) before final acceptance.

## Handoff Rules
- Dev task cannot move beyond `QA` without commit evidence.
- QA must verify reproducible artifacts (test output, logs, or commit trace) before final acceptance.
- Deploy-related tasks require deployment execution evidence against the configured target stack (default `constructos-ws-default` unless user overrides).
