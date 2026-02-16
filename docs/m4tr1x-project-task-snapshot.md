# m4tr1x Project Task Snapshot

Generated: 2026-02-16
Workspace: `10000000-0000-0000-0000-000000000001`
Project: `4c4ed4d1-e493-4986-bc2f-918421ac968c`

## Open

- [ ] `493c3c30-cd6e-440b-94d0-8bcc61ef2388` - QA watch qa-20260214-232522-a808de (`To do`, `Med`)
- [ ] `8de0c53a-9bdf-49d1-9209-cbe95bc07c2c` - QA automation qa-20260214-232522-a808de (`To do`, `Med`)

## Completed

- [x] `b7a8ae4f-7f7d-4ff6-8f30-106d683918e6` - QA schedule qa-20260214-232522-a808de
- [x] `f122ec57-0b02-4c28-b063-a2fc32e14b02` - BUG: Project board/activity/delete workflow broken
- [x] `353aebc2-67e4-48f9-8773-61eeda505857` - BUG: Scheduled/recurring tasks do not execute and re-arm
- [x] `46cb21e6-a933-40d6-871b-a60587be56c6` - BUG: Task create intermittently 500 due to UNIQUE constraint (tasks.id) race
- [x] `55c63f8b-fa40-43f1-8d2f-df1de2c0f600` - BUG: Saved view projection can crash app (UNIQUE constraint saved_views.id)
- [x] `e2afc7be-2b8e-4ad7-9d36-3f31e0036c2d` - BUG: Board mode priority label clipped on task cards
- [x] `ccd026f6-2f3b-4672-8e7a-a2392ebe5474` - FR: Show created time for tasks and notes (list + details)
- [x] `27459953-f964-43aa-93cc-2c616e8d36a9` - FR: Filter tasks and notes by tags
- [x] `a8704fc7-d54f-4f27-8f2a-65ddfc5bc54a` - BUG: Vremenska prognoza 2 scheduled task posts duplicate comments
- [x] `344e5d40-3893-4b8d-878a-263dcb55d681` - BUG: Scheduler reruns completed automation tasks
- [x] `fee81f0b-0646-4905-b5d5-9ffdb5440699` - BUG: Tags treated case-sensitive

## Notes

- Project-deletion model is now hard-delete for project-scoped resources (tasks, notes, saved views, activity rows).
- Resource creation and listing are now project-scoped for tasks and notes.
