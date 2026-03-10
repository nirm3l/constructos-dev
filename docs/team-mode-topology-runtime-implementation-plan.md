# Team Mode Topology and Runtime Implementation Plan

## Goal
Separate Team Mode knowledge-graph structure from runtime automation behavior so that:
- task relationships are visible before kickoff,
- `TaskAutomationRequested` remains the primary runtime communication mechanism,
- status-change triggers remain supported generally, but Team Mode does not depend on them for live orchestration.
- The same classification discipline should also cover adjacent orchestration/plugin behavior that depends on request interpretation, especially Git Delivery and Docker Compose.

## Current Problems
- Team Mode task connectivity in the knowledge graph was historically inferred from `execution_triggers`, but the target model is declarative `task_relationships` for topology and runtime automation events for post-kickoff communication.
- Lead-first kickoff can stall when no deterministic post-kickoff Developer dispatch occurs.
- Runtime communication after kickoff is carried by `TaskAutomationRequested`, but those links are not represented in the knowledge graph.
- Verification still over-emphasizes trigger topology instead of distinguishing structural topology from runtime communication.
- Some runtime decisions still depend on free-text heuristics (for example kickoff instruction recognition in runner paths) instead of structured LLM classification persisted from the request layer.
- Some deterministic evidence readers still use regex/keyword extraction. Those are acceptable only when they parse already-produced artifacts and fail closed; they are not acceptable for request/workflow classification.

## Immediate Fixes

### Done
- Kickoff success now skips Lead deploy/health execution gates for dispatch-only kickoff runs.
- Kickoff success now dispatches initial Developer work deterministically instead of leaving Lead to spin without any Developer automation starting.
- Initial kickoff dispatch respects project automation parallelism and Developer task priority.
- Kickoff-originated Developer dispatches now keep an explicit request source value (`lead_kickoff_dispatch`).
- Remaining gap: any residual orchestration path that still inspects prompt wording directly must be moved to persisted structured classification state, including adjacent Git Delivery and Docker Compose execution decisions.

### Verify in production-like flow
- Re-run the Tetris setup prompt path and confirm that after kickoff:
  - the Lead kickoff task completes as a dispatch-only run,
  - the highest-priority runnable Developer tasks are queued,
  - Lead does not immediately fail on deploy preflight during kickoff.

## Phase 1: Knowledge Graph Structural Topology

### Objective
Represent Team Mode workflow edges before kickoff without relying on executable status-change triggers.

### Implementation
- Introduce a non-executable Team Mode topology projection for project tasks.
- Derive structural workflow edges from Team Mode roles and assignment metadata:
  - Developer -> Lead (`DELIVERS_TO`)
  - Lead -> QA (`HANDS_OFF_TO`)
  - Developer/QA -> Lead (`ESCALATES_TO`) for blocked-work oversight
- Keep these edges available before any automation run happens.

### Candidate implementation options
1. Preferred:
   Add a dedicated task relationship field such as `workflow_links`.
2. Interim:
   Derive Team Mode structural edges at graph-build time from:
   - `assigned_agent_code`
   - role derivation
   - Team Mode project config

## Phase 1.5: Structured LLM Classification Backbone

### Objective
Remove heuristic workflow classification from runtime paths and make request-time structured LLM classification the single source of truth for ambiguous intent decisions.

### Implementation
- Expand structured LLM classification outputs for setup/execution flows so they cover at least:
  - `project_creation_intent`
  - `execution_intent`
  - `execution_kickoff_intent`
  - `task_completion_requested`
  - `execution_mode` (`setup_only`, `setup_then_kickoff`, `kickoff_only`, `resume_execution`, `unknown`)
  - `workflow_scope` (`team_mode`, `single_agent`, `unknown`)
  - language-agnostic extraction of explicit constraints that affect orchestration (for example exact task count, deploy request, requested port) in the same classifier call where possible
- Persist those outputs into command/request/task metadata when they influence later runner behavior.
- Replace runner-side free-text kickoff detection with reads from persisted classification first.
- Keep safe fallback behavior:
  - if classifier output is missing/invalid/uncertain, return `unknown` and do not dispatch kickoff automatically.
- Minimize query count by batching multiple orchestration decisions into one structured classifier call per user request whenever feasible.
- Treat cache as a secondary optimization:
  - prefer explicit propagation of one classified result through the stack,
  - then use a reusable cache layer to deduplicate unavoidable repeated calls.

### Initial hotspots to replace
- `app/plugins/team_mode/runner.py:is_team_mode_kickoff_instruction(...)`
- any runner path that infers kickoff/resume/setup directly from instruction text
- any manual task automation shortcut that infers completion/done intent from instruction text instead of persisted structured classification
- any Team Mode setup summary path that marks kickoff successful without checking structured execution mode + persisted automation state
- any Git Delivery / Docker Compose setup-or-execute decision that still depends on prompt keywords instead of structured classifier output

### Acceptance criteria
- Different phrasings of the same kickoff request produce the same dispatch behavior.
- Different languages expressing the same request produce the same dispatch behavior.
- Runner does not need to parse free text to decide whether a completed Lead run was a kickoff cycle.
- Classifier failure results in safe non-dispatch, not heuristic guessing.
- Evidence extraction helpers remain clearly scoped to artifact parsing and are not reused as fallback intent classifiers.
- The same instruction should not be reclassified in multiple layers when a persisted structured result is already available.
- If repeated classification is temporarily unavoidable, a shared cache layer should absorb duplicate calls without changing behavior.

## Phase 1.6: Reusable Classification Cache and Duplicate-Call Audit

### Objective
Reduce unnecessary classifier calls across the project without weakening the classify-once architecture.

### Implementation
- Audit every orchestration and task-automation entry point and label it as either:
  - primary classification point,
  - structured classification consumer only,
  - invalid duplicate classification path.
- Introduce a shared reusable classification cache abstraction rather than feature-specific cache logic.
- Standardize cache key shape to include:
  - normalized instruction payload,
  - `workspace_id`,
  - `project_id`,
  - classifier/schema version.
- Add lightweight observability so duplicate classification of the same instruction can be detected in logs or counters.
- Convert remaining lower-level classifier calls into:
  - direct consumption of persisted structured classification when available,
  - cached fallback only when no upstream structured result exists.

### Acceptance criteria
- The same request is classified once in the normal happy path for chat, MCP task runs, and REST task runs.
- Remaining repeated classifier calls are intentional, measurable, and cache-backed.
- The cache implementation is reusable across Team Mode, Git Delivery, Docker Compose, and general task automation flows.
- Cache failure or invalid cache data does not change correctness; it only removes the optimization benefit.

## Phase 2: Knowledge Graph Runtime Communication Edges

### Objective
Represent what actually happened during execution.

### Implementation
- Teach the graph builder to ingest runtime communication from task automation events/state:
  - `TaskAutomationRequested`
  - `source_task_id`
  - `reason`
  - `trigger_link`
  - `correlation_id`
  - `lead_handoff_token`
- Add runtime edges such as:
  - `REQUESTED_AUTOMATION_FOR`
  - `HANDED_OFF_TO`
  - `ESCALATED_TO`

### Notes
- Runtime communication edges must coexist with structural topology edges.
- Structural edges answer "how this workflow is wired".
- Runtime edges answer "what happened in this run".

## Phase 3: Team Mode Verification Cleanup

### Objective
Make verification reflect the new split cleanly.

### Implementation
- Keep topology checks mandatory for Team Mode.
- Stop treating trigger execution as the primary orchestration model.
- Add runtime communication visibility separately from topology checks.
- Ensure direct `TaskAutomationRequested` remains authoritative for execution.
- Add visibility for classifier-derived execution mode so operators can distinguish:
  - classified kickoff,
  - classified resume,
  - setup-only request,
  - unknown/safe-negative result.

## Phase 4: Lead Dispatch Planning

### Objective
Scale kickoff and follow-up dispatch beyond the current small seeded task set.

### Implementation
- Build a deterministic Lead dispatch planner that:
  - ranks runnable Developer tasks by priority,
  - respects project parallelism,
  - respects Developer slot availability,
  - avoids double-booking the same Developer slot,
  - can support larger queues (for example 30 tasks).
- Reuse the same planner for:
  - initial kickoff dispatch,
  - post-blocker corrective dispatch,
  - recurring Lead oversight cycles.

## Phase 5: Compose Synthesis

### Objective
Unblock first deploy cycles when no compose manifest exists.

### Implementation
- Implement Lead-owned compose synthesis from repository/runtime evidence.
- Commit compose changes on a task branch.
- Merge deterministically to `main`.
- Continue deploy and QA handoff after merge.

## Required Tests
- Kickoff dispatch queues initial Developer work by priority.
- Kickoff does not run Lead deploy preflight.
- Different kickoff phrasings map to the same structured execution classification and produce the same dispatch result.
- Structural Team Mode graph edges exist before kickoff.
- Runtime communication graph edges appear after `TaskAutomationRequested`.
- Equivalent status-trigger requests are ignored or deduplicated when direct communication already exists.
- Lead recurring cycles reuse the same dispatch planner and do not starve Developer work.
