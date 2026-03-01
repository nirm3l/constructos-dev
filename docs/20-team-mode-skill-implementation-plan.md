# Team Mode Skill: Analysis and Implementation Plan

## 1. Objective
Introduce a new seeded workspace skill (`team_mode`) that orchestrates project delivery with a virtual team:
- Delivery Lead Agent
- Implementation Agent Alpha
- Implementation Agent Beta
- Quality Assurance Agent

Target behavior:
- Task implementation through feature branches.
- Task lifecycle controlled by board statuses.
- Automated runs triggered by status changes and/or schedules.
- Team Lead oversight via recurring scheduled automation.
- QA automated validation and bug reporting.
- Escalation path from Team Lead to a human member when blocked.
- Increase parallel automation execution from 3 to 4.

## 2. Current Application Fit (What Already Exists)

### 2.1 Skills and seeding
- Workspace skill seeds already exist and are auto-loaded from:
  - `app/shared/workspace_skill_seeds/*.md`
- Current seeded skills:
  - `github_delivery.md`
  - `jira_execution.md`
- Seed loader and catalog bootstrap already support adding one more seed file:
  - `app/shared/bootstrap.py`

### 2.2 Automation engine and triggers
- Tasks support `instruction` + `execution_triggers` with:
  - `manual`
  - `schedule`
  - `status_change`
- Trigger normalization and validation already exist:
  - `app/shared/task_automation.py`
  - `app/features/tasks/command_handlers.py`
- Scheduled automation can be recurring (`recurring_rule`) and status-gated (`run_on_statuses`).
- Cross-task status-change triggers already exist via external selector logic:
  - `app/shared/eventing_task_automation_triggers.py`

### 2.3 Runner concurrency
- Current default max parallel automation is 3:
  - `AGENT_RUNNER_MAX_CONCURRENCY` in `app/shared/settings.py`
- Runner uses this cap directly:
  - `app/features/agents/runner.py`

### 2.4 Team and ownership primitives
- Tasks already support `assignee_id`.
- Projects already support custom board statuses.
- Non-human users are supported (`user_type = agent`), but automation execution is currently attributed to one system agent (`codex-bot`).
- Project memberships already support role values and can be used for behavior routing.

## 3. Key Gaps for Full Team Mode

1. Role identity routing gap:
- Runner events are emitted under one system actor.
- Without enhancement, Lead/Dev/QA are conceptual roles in instructions, not true per-role execution identities.

2. Branching policy is instruction-only today:
- GitHub flow exists as guidance in skill text.
- There is no strict backend policy guard forcing feature-branch naming or per-task branch linkage.

3. QA verification loop is not explicit:
- QA can be done by instruction (Playwright/script-based), but there is no first-class QA execution policy abstraction yet.

## 4. Recommended Design

### 4.1 Keep Team Mode as a seeded skill first
Add `team_mode.md` in workspace seed directory so every workspace gets a consistent baseline.

### 4.1.1 Agent roster and naming
Define and manage a dedicated Team Mode agent roster:
- Delivery Lead Agent
- Implementation Agent Alpha
- Implementation Agent Beta
- Quality Assurance Agent

These should be workspace users with `user_type = agent`.

### 4.1.2 Role-driven behavior model (preferred)
Use project membership role values to define behavior policy for each agent instead of hardcoding per-user logic.

Recommended Team Mode project roles:
- `TeamLeadAgent`
- `DeveloperAgent`
- `QAAgent`

Suggested mapping:
- Delivery Lead Agent -> `TeamLeadAgent`
- Implementation Agent Alpha -> `DeveloperAgent`
- Implementation Agent Beta -> `DeveloperAgent`
- Quality Assurance Agent -> `QAAgent`

### 4.1.3 Team Mode enablement contract
When Team Mode skill is applied and enabled on a project, the system must:
1. Ensure all four Team Mode agents exist in the workspace.
2. Ensure all four Team Mode agents are assigned as project members.
3. Ensure expected project role mapping is applied to those members.
4. Keep assignment idempotent (safe on repeated apply).

### 4.2 Model roles through assignment + trigger conventions
Use explicit task conventions:
- Lead tasks: scheduled/recurring, assignee = Delivery Lead Agent
- Dev tasks: status-triggered/manual, assignee = Implementation Agent Alpha/Beta
- QA tasks: status-triggered after implementation status transitions, assignee = Quality Assurance Agent

This uses existing primitives with minimal backend risk.

### 4.3 Treat branch workflow as enforced guidance before hard policy
Phase 1: enforce through skill text + project rules.
Phase 2 (optional): add backend checks (branch naming/external ref requirements) if needed.

### 4.4 Escalation path
Keep explicit escalation rule in Team Lead instructions:
- If unresolved blocker persists, assign task to human member and move status to configured escalation lane.

## 5. Implementation Plan

## Phase 0: Skill and policy definition
1. Create seeded skill file:
- `app/shared/workspace_skill_seeds/team_mode.md`

2. Skill content should define:
- Role responsibilities (Lead/Dev/QA).
- Canonical Team Mode agent roster names.
- Required Team Mode project membership roles.
- Required status transitions for each role.
- Feature branch convention per task (for example `feature/task-<id>-<slug>`).
- Required task external refs (commit/PR links).
- Merge/rebase conflict handling expectations.
- QA execution strategy fallback order:
  - Existing project test scripts
  - Playwright smoke/e2e
  - Manual API/health checks
- Escalation rule to human assignee.
- Deployment rule for Team Lead using existing Docker Compose project scope (`constructos-app`) only.

3. Add/update docs section describing Team Mode skill usage.

4. Add Team Mode apply semantics:
- Applying Team Mode must reconcile roster users and project membership before task automation starts.
- Failure to assign required agents should fail Team Mode enablement with a clear error.

## Phase 1: Concurrency uplift (3 -> 4)
1. Change default:
- `app/shared/settings.py`
  - `AGENT_RUNNER_MAX_CONCURRENCY` default from `3` to `4`

2. Verify runner behavior remains bounded:
- `app/features/agents/runner.py`
  - No logic rewrite required; cap is already read from setting.

3. Add/adjust tests asserting effective worker cap behavior.

## Phase 2: Team workflow template (recommended)
1. Add optional project template variant (for faster adoption) that seeds:
- Team Lead recurring oversight tasks.
- Developer implementation tasks.
- QA verification tasks.
- Status-change triggers wiring between Dev -> QA -> Lead follow-up.

2. Ensure template-generated tasks include:
- `instruction`
- `execution_triggers`
- `assignee_id`
- target statuses aligned with project board.

Touchpoints:
- `app/features/project_templates/catalog.py`
- `app/features/project_templates/application.py`

## Phase 3: Identity-aware execution (important for audit quality)
1. Introduce role-to-agent identity mapping strategy:
- Preferred: map behavior by project membership role (`TeamLeadAgent`, `DeveloperAgent`, `QAAgent`) and resolve effective actor from task assignee.
- Fallback: map by explicit `assignee_id`.
- Optional fallback: map by task label/metadata (for example `role:qa`) when assignee is not set.

2. Update automation event metadata to reflect effective actor identity (Lead/Dev/QA agent) instead of always system bot.

3. Keep system fallback when mapping is missing.

Touchpoints:
- `app/features/agents/runner.py`
- `app/features/agents/executor.py`
- `app/shared/bootstrap.py` (seed additional agent users if needed)
- `app/features/projects/application.py` and `app/features/projects/command_handlers.py` (project member role assignment/reconciliation)
- `app/features/project_skills/application.py` (enforce Team Mode apply contract)

## Phase 4: QA execution hardening
1. Add standardized QA instruction contract (expected output format: pass/fail, bug list, evidence).
2. Provide reusable QA task instruction snippets in skill content.
3. If Playwright is available in project, require artifact links (trace/video/screenshot) in task comments or refs.

## Phase 5: Optional hard policy guardrails
Implement stricter policy only if teams need stronger enforcement:
- Require commit/PR external refs before moving to final status.
- Validate branch naming pattern in automated workflow comments/refs.
- Block closure when QA evidence is missing.

## 6. Proposed Team Mode Task-State Flow

Recommended default statuses:
- `To do`
- `In progress`
- `In review`
- `QA testing`
- `Done`
- `Blocked`
- `Escalated`

Recommended flow:
1. Dev task enters `In progress` -> implementation on feature branch starts.
2. Dev completes implementation -> move to `In review` with commit/PR refs.
3. QA task trigger watches Dev task transition to `In review` -> QA runs.
4. QA pass -> move target task to `Done`.
5. QA fail -> create/update bug task, move impacted task to `Blocked`.
6. Team Lead recurring oversight task checks blocked/escalated tasks.
7. If unresolved -> assign to human and move to `Escalated`.

## 7. Testing Plan
1. Unit tests:
- Seed loading for `team_mode.md`.
- Trigger validation for status-change and schedule scenarios used by Team Mode.
- Runner concurrency default = 4.

2. Integration tests:
- End-to-end chain: Dev status transition triggers QA task queue.
- Recurring Team Lead scheduled task re-queues correctly.
- Escalation updates assignee/status as defined.
- Team Mode apply auto-creates/attaches required agent users to project memberships.
- Re-applying Team Mode is idempotent (no duplicate members, consistent roles).

3. Non-regression:
- Existing GitHub/Jira seeded skills still load unchanged.
- Existing manual/scheduled automations remain behaviorally identical.

## 8. Rollout Strategy
1. Release Team Mode skill + concurrency uplift first.
2. Observe automation queue depth, failure rate, and average completion time.
3. Enable identity-aware execution next (if audit traceability is required immediately, prioritize this earlier).
4. Add hard policy guardrails only after baseline workflow stabilizes.

## 9. Practical Recommendations
1. Start with instruction-driven orchestration (fastest value, low risk).
2. Keep role execution auditable by implementing per-role actor mapping early.
3. Do not over-enforce branch policies in phase 1; use project rules + skill text first.
4. Keep Team Lead deployment instructions explicitly scoped to app stack (`constructos-app`) to avoid control-plane impact.

## 10. Acceptance Criteria
Team Mode is considered complete for initial rollout when:
1. `team_mode` appears in seeded workspace skills for new/existing workspaces.
2. Default automation parallelism is 4.
3. Enabling Team Mode guarantees required agents are project members with expected Team Mode roles.
4. A project can run Lead/Dev/QA workflow via triggers and scheduled tasks without manual runner intervention.
5. QA can automatically report verification outcomes and create/track bugs.
6. Team Lead can escalate blocked work to a human member through defined status + assignee transition.
