# Team Mode and UI Update Summary

## Completed
1. Team Mode was introduced as a seeded workspace skill (`team_mode`).
2. Seeded skill sync was improved so existing seeded records are refreshed when seed content changes.
3. Team Mode apply contract was implemented:
   - ensures required agent users exist,
   - ensures workspace/project membership,
   - ensures expected Team Mode project roles,
   - remains idempotent on re-apply.
4. Default automation parallelism was increased from `3` to `4`.
5. Automation actor attribution was improved:
   - runner now attributes task automation events/comments to the assigned Team Mode agent when valid,
   - safe fallback to system bot remains.
6. Executor context was improved:
   - added `Current User Project Role` context for prompts (`TeamLeadAgent`, `DeveloperAgent`, `QAAgent`).

## Team Mode Agent Roster
- `M0rph3u5` (`TeamLeadAgent`)
- `Tr1n1ty` (`DeveloperAgent`)
- `N30` (`DeveloperAgent`)
- `0r4cl3` (`QAAgent`)

## New UI Behavior
1. Markdown fullscreen was fixed globally across editor contexts.
2. Fullscreen now works reliably in constrained containers/overlays (including Skills Catalog editors).
3. Fullscreen behavior now uses native Fullscreen API with fallback, improving consistency across views.

## Deployment
1. Changes were deployed.
2. Current running backend version: `0.1.672`.
