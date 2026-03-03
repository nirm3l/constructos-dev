Execution intent detected for this project.
Required behavior:
- Treat this as implementation execution kickoff/resume, not Team Mode setup.
- Do not create/recreate project and do not re-attach/re-apply skills if already configured.
- First read current tasks and run verify_team_mode_workflow + verify_delivery_workflow.
- If verification passes, execute existing workflow tasks and persist progress.
- Only patch missing prerequisites when verification fails.
- Completion contract for execution kickoff:
  1) Implement the planned scope for active Dev tasks.
  2) Run tests/validation and include concrete results.
  3) Update task statuses based on real outcomes.
  4) Provide artifact evidence per task (patch/commit/log/link).
- If any item cannot be completed, return BLOCKED with concrete missing prerequisite(s).
- Report concrete mutations and final persisted task state.
