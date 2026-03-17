# Team Mode V2 Source of Truth

## Status
- Authoritative for the next Team Mode rewrite.
- No backward compatibility is required.
- Legacy Team Mode behavior may be removed instead of migrated.
- Target deployment model is recreate-from-zero after implementation is complete.

## Goal
Replace the current role-task workflow (`Dev -> Lead -> QA` as separate task/status phases) with a more natural single-task lifecycle:
- one implementation task moves between agents,
- authority role changes behavior, not task type,
- Developer owns implementation and merge,
- Lead is a project-level controller plus escalation/deploy owner,
- QA validates deployed work on the same task,
- human involvement happens only when Lead cannot resolve a blocker.

## Core Decisions
- Team Mode no longer creates role-specific tasks.
- Team Mode no longer depends on role-specific task statuses.
- Team Mode no longer uses `workflow.transitions` or any generic "allowed transitions" matrix.
- A task's active behavior is determined by the current assignee's authority role.
- There is always exactly one Team Lead agent per Team Mode project.
- Lead oversight is project-scoped, not task-scoped.
- Assignment to an agent is an execution trigger.
- Tags remain visible UX markers, but they must not be the only source of truth for automation decisions.

## Resolved Ambiguities

### Terminal status
Your notes mention both `Done` and `Completed`. This spec standardizes on the semantic terminal state `completed`.

Implementation rule:
- Team Mode must use explicit status semantics instead of hardcoded status names.
- Mandatory standard statuses for new Team Mode projects:
  - `To do`
  - `In Progress`
  - `In Review`
  - `Blocked`
  - `Awaiting decision`
  - `Completed`
- Team Mode may allow additional project-specific statuses, but these mandatory standard statuses must always exist.
- Project-specific statuses must not replace the mandatory Team Mode semantic statuses.
- Team Mode runtime must never infer status meaning heuristically from arbitrary status text.

### "Available agent"
`Available` must be deterministic, not guessed.

Implementation rule:
- Developer and QA auto-assignment use `least_active_then_stable_order`.
- Active means the agent currently owns a non-terminal task in `To do`, `In Progress`, or `Blocked`.
- Stable tie-breaker is the agent order stored in Team Mode config.

### Completion notification ownership
Your notes imply both QA and Lead may notify on project completion. That would create duplicates.

Implementation rule:
- The last successful QA completion emits a `project_completion_candidate` signal.
- The Lead controller performs the authoritative finalization exactly once:
  - send the user notification,
  - create the final report note,
  - update the project external link.
- The finalization path must be idempotent and deduped.

### Tags as workflow state
Plain editable tags are too fragile to be the only automation state.

Implementation rule:
- Team Mode stores structured lifecycle fields in task state.
- Reserved visible tags mirror those lifecycle fields for UX.
- Automation reads structured state first and tags second.

## Team Invariants
- Exactly `1` Lead agent is required.
- At least `1` Developer agent is required.
- At least `1` QA agent is required.
- Every Team Mode project must have one resolved human owner for escalation and completion notifications.
- Each agent has exactly one authority role:
  - `Developer`
  - `QA`
  - `Lead`
- A task does not carry a permanent workflow role.
- Legacy `tm.role:*` task labels are removed as workflow truth.
- Legacy status fallback for role derivation is removed.

## Team Mode Config V2
`team_mode` config must be simplified to role coverage, semantics, assignment policy, optional review gate, and Lead oversight.

Suggested canonical shape:

```json
{
  "team": {
    "agents": [
      { "id": "dev-a", "name": "Developer A", "authority_role": "Developer", "executor_user_id": "..." },
      { "id": "dev-b", "name": "Developer B", "authority_role": "Developer", "executor_user_id": "..." },
      { "id": "qa-a", "name": "QA A", "authority_role": "QA", "executor_user_id": "..." },
      { "id": "lead-a", "name": "Lead", "authority_role": "Lead", "executor_user_id": "..." }
    ]
  },
  "status_semantics": {
    "todo": "To do",
    "active": "In Progress",
    "in_review": "In Review",
    "blocked": "Blocked",
    "awaiting_decision": "Awaiting decision",
    "completed": "Completed"
  },
  "routing": {
    "developer_assignment": "least_active_then_stable_order",
    "qa_assignment": "least_active_then_stable_order"
  },
  "oversight": {
    "reconciliation_interval_seconds": 5,
    "human_owner_user_id": "..."
  },
  "labels": {
    "merged": "merged",
    "deploy_ready": "deploy-ready",
    "deployed": "deployed",
    "tested": "tested"
  }
}
```

Removed from config:
- `workflow.transitions`
- `governance.merge_authority_roles`
- `governance.task_move_authority_roles`
- `automation.lead_recurring_max_minutes`

## Canonical Status Model
Team Mode uses semantic states, not role phases.

Required semantic states:
- `todo`
- `active`
- `in_review`
- `blocked`
- `awaiting_decision`
- `completed`

Rules:
- New implementation tasks start in `todo`.
- Any agent actively working a task moves it to `active`.
- `in_review` means the task is waiting for explicit human review approval.
- `blocked` means an agent cannot continue and requires Lead triage.
- `awaiting_decision` means the task is now owned by a human and Team Mode pauses further agent execution.
- `completed` is terminal and means QA verified the deployed outcome successfully.
- Additional custom project statuses may exist, but Team Mode lifecycle logic must continue to anchor on the mandatory semantic statuses above.

## Reserved Lifecycle Labels
Visible labels must be normalized lowercase and reserved for Team Mode automation.

Canonical labels:
- `merged`
- `deploy-ready`
- `deployed`
- `tested`

Lifecycle rules:
- Developer success adds `merged` and `deploy-ready`.
- Lead successful deploy removes `deploy-ready` and adds `deployed`.
- QA success adds `tested`.
- When a completed or deployed task is reopened for a new fix cycle:
  - remove `merged`,
  - remove `tested`,
  - remove `deployed`,
  - remove `deploy-ready`,
  - clear current-cycle deploy/test/review state,
  - reset the task phase to `implementation`,
  - move the task back to `To do` or `In Progress` as appropriate for the new cycle,
  - preserve immutable audit history and prior notes.

## Structured Task State
Task state must carry authoritative lifecycle fields.

Minimum required fields:
- `team_mode_current_role`
  - derived from current assignee authority role, not user-editable
- `team_mode_phase`
  - `implementation`
  - `in_review`
  - `deploy_ready`
  - `deployment`
  - `qa_validation`
  - `blocked`
  - `awaiting_decision`
  - `completed`
- `last_merged_at`
- `last_merged_commit_sha`
- `last_deploy_cycle_id`
- `last_deployed_at`
- `last_deploy_execution`
- `last_tested_at`
- `last_human_escalated_at`
- `last_review_requested_at`
- `last_review_approved_at`
- `project_completion_finalized_at`

Tags are mirrored from these fields, not the other way around.

## Task Notes by Role
Each Team Mode task may link one or more notes, and notes are the preferred place for phase-specific detail.

Rules:
- Team Mode should support role-based note grouping or typed notes so the task note list does not become unstructured noise.
- Recommended default note groups:
  - `Developer`
  - `Lead`
  - `QA`
  - `Review`
- Developer may write implementation notes, validation notes, and merge evidence notes.
- Lead may write deploy notes, blocker-resolution notes, and finalization notes.
- QA may write validation notes and PASS/FAIL evidence notes.
- Human reviewers may write review notes and approval/rejection notes.
- Structured task state remains authoritative for automation.
- Notes are supporting evidence and human-readable history, not the primary workflow state machine.

## Assignment and Execution Rules

### Universal rule
- Assigning a task to an agent queues execution immediately.
- Assigning a task to a human never auto-queues execution.

### Default task creation
- A newly created Team Mode task is neutral and implementation-scoped.
- It is auto-assigned to a Developer by `least_active_then_stable_order`.
- It starts in `todo`.
- The first Developer run moves it to `active`.

### Reassignment by role
- Developer -> Lead:
  - used for deploy-ready handoff or blocker escalation
- Lead -> QA:
  - used after successful deploy
- QA -> Lead:
  - used when QA cannot continue and needs Lead triage
- Lead -> Human:
  - used for `Awaiting decision`
- Lead -> Developer:
  - used when Lead triages a blocker and returns the task with clarified instructions

## Single-Task Lifecycle

### 1. Creation
- Human or setup flow creates a task with implementation scope.
- Task is assigned to a Developer automatically.
- Status = `todo`.
- Phase = `implementation`.

### 2. Developer execution
- Developer starts work and moves task to `active` if not already there.
- Developer implements on the task branch.
- Developer runs validation required by Git Delivery policy.
- If human code review is disabled:
  - Developer merges the task branch to `main` after successful validation.
- If human code review is enabled:
  - Developer moves the task to `In Review`,
  - review approval is recorded,
  - Developer performs the final merge-to-main after approval.
- Developer records merge evidence on the task.
- Developer adds:
  - `merged`
  - `deploy-ready`
- Developer assigns the task to Lead.
- Status remains `active`.
- Phase becomes `deploy_ready`.

### 3. Lead deployment cycle
- Lead controller sees tasks assigned to Lead with phase `deploy_ready`.
- Deployment runs one task at a time.
- Lead prepares or validates deploy assets.
- Managed deployment is executed by the runner, not by a scheduled Lead task.
- On successful deploy:
  - set `last_deploy_cycle_id`,
  - persist deploy evidence,
  - remove `deploy-ready`,
  - add `deployed`,
  - assign task to QA,
  - keep status as `active`,
  - phase becomes `qa_validation`.

### 4. QA validation
- QA validates the deployed runtime only.
- QA must not rebuild, re-merge, or redeploy as part of normal validation.
- On success:
  - add `tested`,
  - status = `completed`,
  - phase = `completed`.

### 5. Completion finalization
- If that QA completion made all non-archived Team Mode tasks `completed`:
  - emit `project_completion_candidate`,
  - Lead controller finalizes the project exactly once.

## Blocker Policy

### Phase 1 rule
- Persisted retry logic is out of scope for phase 1.
- The workflow engine does not track retry counts in phase 1.
- An agent may self-correct within a single run, but if it still cannot continue, the task becomes `blocked` and goes to Lead triage.

### Developer blocker policy
- If Developer cannot continue:
  - status = `blocked`
  - assign task to Lead
  - phase = `blocked`

### QA blocker policy
- If QA cannot continue:
  - status = `blocked`
  - assign task to Lead
  - phase = `blocked`

### Lead blocker policy
- Lead reviews blocked tasks with broader repository, runtime, and workflow context.
- In phase 1, Lead is a triage/orchestration role for blocked tasks, not a coding role.
- Lead may:
  - clarify the blocker and return the task to Developer,
  - resolve process/deploy coordination issues that do not require taking over implementation work,
  - deploy and assign to QA,
  - or escalate to a human.
- Lead must not directly implement and commit code for a blocked task in phase 1.
- If Lead cannot resolve without human input:
  - assign task to the configured human owner,
  - status = `awaiting_decision`,
  - phase = `awaiting_decision`,
  - send notification immediately.

## Lead Controller
Lead is no longer a recurring scheduled task. Lead is a project-level controller.

### Responsibilities
- watch all Team Mode tasks in the project,
- react when a task is assigned to Lead,
- react when tasks become `deploy_ready`,
- react when tasks become `blocked`,
- reconcile project completion,
- create final report note and update project external link.

### Triggers
- event-driven wakeups on:
  - task creation,
  - assignment change,
  - status change,
  - lifecycle label change,
  - task automation completion/failure
- periodic reconciliation every `5` seconds for active Team Mode projects only

### Reconciliation cost rule
- The 5-second reconciliation loop must not trigger LLM execution by default.
- Its default responsibility is lightweight database/state inspection.
- Expensive actions such as LLM execution, deploy, or notification fan-out must happen only when the reconciliation logic detects a real state transition or stale condition that requires action.

### Active project definition
A project is active for Lead reconciliation while at least one task is:
- not `completed`,
- not archived,
- or waiting for deployment/finalization.

Project completion may not finalize while any non-archived task is in:
- `To do`
- `In Progress`
- `In Review`
- `Blocked`
- `Awaiting decision`

### Safety rules
- Use a per-project lease so only one Lead controller cycle mutates a project at a time.
- Reconciliation must be idempotent.
- Periodic scan is a recovery path, not the primary orchestrator.

## Context Partitioning and Prompt Assembly
Prompt instructions must be partitioned by invocation origin.

### Application chat context
When execution starts from the application chat:
- include setup instructions for Team Mode project creation or reconfiguration,
- include kickoff instructions,
- include project-level orchestration rules,
- do not include Developer, QA, or Lead task-execution behavior packs,
- do not include role-specific implementation, QA, or deployment instructions.

Application chat is responsible for:
- project setup,
- configuration repair,
- kickoff,
- progress reporting,
- high-level orchestration decisions.

Application chat is not responsible for:
- acting as Developer,
- acting as QA,
- acting as Lead on a specific task execution run.

### Automation task context
When execution starts from task automation:
- do not include setup instructions,
- do not include project-creation instructions,
- do not include interactive kickoff instructions,
- include only task-execution instructions and role-behavior rules.

Automation task context is responsible for:
- executing the assigned task,
- following the current assignee authority role,
- obeying role-specific gates and lifecycle rules,
- handing the task off correctly when the role changes.

### First-prompt rule for a task
The first prompt for a given task must include the complete Team Mode role-behavior pack for all task-execution roles:
- `Developer`
- `Lead`
- `QA`

Reason:
- the same task will move between agents over time,
- the task may start with Developer, then move to Lead, then to QA,
- the task context must already contain the behavioral contract for every role that may later own the task.

### Current-role emphasis rule
Even though all role packs are present in the first task prompt:
- the currently assigned authority role must be marked as the active role,
- the active role instructions must appear first and be visually/logically emphasized,
- the non-active role instructions must remain present as future-state behavior rules,
- the executor must follow only the instructions for the current assigned authority role, except where a cross-role handoff rule explicitly applies.

### Reassignment rule
On every automation run after reassignment:
- rebuild prompt context using the current assignee authority role,
- keep the complete multi-role task behavior contract available,
- re-emphasize the new active role at the top of the prompt,
- never rely on setup or kickoff instructions inside task automation context.

### Compaction rule
If task thread context is compacted or resumed:
- the compacted context must preserve the multi-role task behavior contract,
- the compacted context must preserve the current active authority role,
- compaction may summarize prior execution history,
- compaction may not drop role-behavior instructions needed for future reassignment of the same task.

## Role-Specific Prompt and Gate Model
Authority role changes the prompt pack, gate pack, and allowed actions.

### Developer
Prompt responsibilities:
- implement requested scope,
- run required validation,
- merge to `main` when complete,
- attach merge evidence,
- never deploy.

Hard gates:
- no completion without implementation evidence,
- no merge without required validation,
- no deploy authority,
- after merge, must hand off to Lead.

### QA
Prompt responsibilities:
- validate the already deployed runtime,
- attach verifiable PASS/FAIL artifacts,
- never merge,
- never deploy,
- escalate to Lead when QA cannot continue.

Hard gates:
- QA cannot start without deploy evidence for the current cycle,
- QA cannot mark `completed` without artifacts,
- QA cannot perform merge or deploy actions.

### Lead
Prompt responsibilities:
- supervise all project tasks,
- handle tasks explicitly assigned to Lead,
- deploy `deploy-ready` work,
- resolve blocked work,
- escalate unresolved items to a human,
- finalize project completion.

Hard gates:
- exactly one Lead exists,
- Lead may deploy but is not required to own a dedicated task,
- Lead may set `awaiting_decision`,
- Lead is the only agent role allowed to finalize project completion.
- Lead must not directly implement and commit blocked-task code in phase 1.

## Optional Human Code Review Gate
Human code review is an optional project-level policy and is disabled by default.

Rules:
- `human_code_review_required` must be configurable per project.
- Default is `false`.
- When enabled, Developer may not perform the final merge-to-main until human review approval is recorded.
- `In Review` is the explicit status used for this gate.
- Human review must be modeled as an explicit gate, not hidden prompt behavior.
- Human review must not reuse `Awaiting decision`.
- Recommended flow when review is required:
  - Developer finishes implementation and validation,
  - task moves to `In Review`,
  - review approval is recorded,
  - Developer performs final merge-to-main,
  - task continues to Lead with `deploy-ready`.

## Merge and Deploy Rules
- Developer owns merge-to-main.
- Lead owns deployment.
- QA owns verification.
- Merge authority is no longer configurable in Team Mode plugin policy.
- Lead must never be the default merge owner.

Developer merge contract:
- branch must be the task branch,
- validation must be green when required,
- merge evidence must be written to task state and refs,
- if human code review is required for the project, review approval must be recorded before merge,
- after merge, the task must be handed to Lead with `deploy-ready`.

Lead deploy contract:
- the selected task must already be merged,
- deployment must produce structured deploy evidence,
- each deploy cycle belongs to one task,
- after successful deploy the task is assigned to QA.

## Consistency and Deployment Freeze
Deployment must run under a project-scoped consistency lock.

### Project deploy lock
- Before Lead starts a deploy cycle, the system must acquire a project-scoped deploy lock.
- The lock must cover:
  - task selection for the deploy cycle,
  - deploy execution,
  - deploy evidence persistence,
  - lifecycle/tag updates for the deployed task,
  - reassignment of the deployed task to QA.
- Every deploy cycle must have:
  - `deploy_cycle_id`
  - `deploy_lock_id`
  - `deploy_lock_acquired_at`
  - `deploy_lock_released_at`

### Code freeze rules during deploy
While the deploy lock is active for a project:
- no Developer merge-to-main is allowed for that project,
- no new task may enter the active deploy cycle,
- no lifecycle mutation may move the locked task back out of the deploy cycle,
- no concurrent Lead deploy cycle may start for the same project.

Allowed during deploy lock:
- Developers may continue working on task branches,
- new merge-ready work may accumulate outside the current deploy cycle,
- tasks that become merge-ready during the lock wait for the next deploy cycle.

### Atomicity rule
The following must be treated as one consistent deploy-finalization section:
- resolve deploy target,
- execute deploy,
- persist deploy outcome,
- remove `deploy-ready`,
- add `deployed`,
- assign the task to QA,
- emit any deploy-cycle events.

The system must not allow a partial finalization where deploy succeeded but task state/tag updates reflect a different task snapshot.

### Lock failure and recovery
- Deploy lock must be lease-based, not permanent.
- If the process crashes or stalls, the lock must expire safely.
- Lead reconciliation must be able to detect a stale deploy lock and recover or mark the cycle failed.
- Recovery must not silently duplicate lifecycle changes or QA handoffs for the same deploy cycle.

### Merge conflict prevention rule
- If a Developer finishes validation while a deploy lock is active, merge-to-main must be rejected with a deterministic "deployment in progress" outcome.
- The Developer keeps merge evidence ready and re-attempts handoff after the deploy lock is released.

## Notifications

### Awaiting decision
When Lead escalates to a human:
- send one in-app notification immediately,
- include task id, title, current blocker summary, and why human input is required,
- use dedupe key based on task id plus escalation timestamp/version.

`Awaiting decision` blocks final project completion until the task is resolved and eventually reaches `Completed`.

### Project completion
When all Team Mode tasks are terminal:
- send one in-app notification to the human owner,
- create one project-level note with the final report,
- update the project external link to the live deployment URL or other authoritative release URL,
- use a dedupe key based on project id plus completion cycle id.

## Final Report Note
Lead finalization creates one project note titled with the completion cycle timestamp.

Minimum content:
- project name,
- completed task list,
- merged commits,
- deploy cycle ids,
- deployment URL,
- QA evidence summary,
- blocker/escalation summary,
- completion timestamp.

## Verification Model V2
Legacy topology verification no longer applies.

Required Team Mode checks should become:
- `single_lead_present`
- `developer_coverage_present`
- `qa_coverage_present`
- `human_owner_present`
- `status_semantics_defined`
- `lead_controller_enabled`
- `assignment_trigger_enabled`
- `phase1_blocker_policy_defined`

Removed Team Mode check:
- `required_topology_present`

## Explicit Legacy Removals
Delete these concepts from backend and frontend:
- `Dev` task status as workflow status
- `Lead` task status as workflow status
- `QA` task status as workflow status
- dedicated Lead oversight task
- dedicated QA validation task
- dedicated Developer task type in Team Mode seeding
- `workflow.transitions`
- "allowed transitions" UI editor
- transition-policy enforcement based on Team Mode workflow config
- kickoff model that requires a runnable Lead task
- recurring Lead scheduled task
- topology checks that assume separate Dev/Lead/QA tasks
- role derivation from task status
- role derivation from legacy `tm.role:*` labels
- merge authority defaulting to Lead

## Implementation Surfaces

### Backend
- `app/features/agents/service.py`
  - replace Team Mode config schema validation and defaults
- `app/plugins/team_mode/state_machine.py`
  - remove transition matrix logic
- `app/features/tasks/command_handlers.py`
  - replace transition enforcement with role-action rules
- `app/plugins/team_mode/task_roles.py`
  - remove status fallback and permanent task-role assumptions
- `app/plugins/team_mode/workflow_orchestrator.py`
  - replace Lead-task kickoff logic with project-scoped Lead controller behavior
- `app/plugins/team_mode/api_kickoff.py`
  - stop requiring Lead task kickoff targets
- `app/plugins/team_mode/gates.py`
  - replace topology checks with Team Mode V2 checks
- `app/plugins/team_mode/service_policy.py`
  - replace `open_developer_tasks` and done-transition logic with V2 completion/finalization logic
- `app/features/agents/runner.py`
  - remove Lead-task merge/deploy/handoff assumptions and implement assignment-triggered execution plus project-scoped Lead reconciliation
  - add project-scoped deploy lock and merge freeze enforcement
- `app/features/agents/gates.py`
  - update delivery checks to read merged/deployed/tested lifecycle state instead of role-task topology
- `app/features/tasks/read_models.py`
  - expose structured Team Mode V2 lifecycle fields and gates
- `app/features/projects/task_dependency_graph.py`
  - stop projecting Team Mode as separate Dev/Lead/QA task lanes
- `app/shared/task_relationships.py`
  - keep relationships for real task dependencies only, not role handoff modeling
- `app/shared/prompt_templates/codex/full_prompt.md`
  - keep app-chat Team Mode guidance limited to setup, kickoff, and orchestration
- `app/shared/prompt_templates/codex/resume_prompt.md`
  - keep resumed app-chat Team Mode guidance limited to setup, kickoff, and orchestration
- `app/plugins/team_mode/prompt_templates/`
  - split Team Mode prompt guidance into:
    - app-chat orchestration guidance,
    - task-automation role-behavior guidance
  - ensure task-automation first prompt includes all role packs with current-role emphasis

### Frontend
- `app/frontend/src/components/projects/ProjectsInlineEditor.tsx`
  - remove statuses/transitions editor for Team Mode
  - add Team Mode V2 semantics, optional review gate, single-Lead, and human-owner config
- `app/frontend/src/components/tasks/TasksPanel.tsx`
  - remove transition-driven status affordances
- `app/frontend/src/components/tasks/TaskDrawer.tsx`
  - surface lifecycle state, role-aware reassignment, blocker state, and reserved labels
- `app/frontend/src/components/projects/ProjectTaskDependencyGraphPanel.tsx`
  - stop ranking by `Dev/Lead/QA` status flow

### Tests
Rewrite Team Mode tests around:
- single-task lifecycle,
- assignment-triggered execution,
- Developer merge handoff,
- Lead deploy batching,
- QA completion,
- blocker triage without persisted retry counters,
- human escalation,
- project completion finalization,
- single Lead enforcement,
- removal of transition-matrix behavior.

## Acceptance Criteria
- Team Mode creates neutral implementation tasks only.
- New tasks are auto-assigned to Developers deterministically.
- No Team Mode code path requires `Dev`, `Lead`, or `QA` as statuses.
- No Team Mode code path requires separate Lead or QA tasks.
- Developer performs merge-to-main.
- Lead deploys merged work.
- QA completes the same task after successful validation.
- Lead exists exactly once per project.
- `Awaiting decision` is human-owned and notification-backed.
- Project completion finalization happens exactly once and creates the report note plus project external link.

## Out of Scope
- backward compatibility,
- migration of old Team Mode projects,
- mixed legacy/new Team Mode support,
- preserving old verification contracts that depend on separate role tasks.
