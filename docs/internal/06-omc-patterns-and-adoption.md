# OMC Patterns And Adoption

## Normative Policy (Source of Truth)

- ConstructOS should adopt the strong orchestration patterns found in `oh-my-claudecode` only when they strengthen our existing persisted workflow model, plugin policy model, and graph-grounded context model.
- ConstructOS must not clone OMC's file-local state model, CLI-specific runtime assumptions, or keyword-heavy orchestration UX as system-of-record behavior.
- Preferred adoption shape is: reimplement the pattern inside ConstructOS primitives, not wrap or call OMC.
- Team Mode, Git Delivery, Docker Compose, graph context, and project setup orchestration remain the authoritative workflow core.
- For ambiguous workflow classification and kickoff decisions, keep using structured LLM classification and safe-negative outcomes rather than heuristic fallback.
- New orchestration UX should produce persisted evidence, observable execution state, and explicit recovery points.

## Executive Conclusion

OMC is strongest in five areas that ConstructOS can use immediately:

1. Explicit execution-mode state and phase transitions.
2. Lightweight task sizing and decomposition before over-orchestrating.
3. Reusable learned skills with automatic context injection.
4. First-class verification loops with visible evidence.
5. Better operator visibility through mission/worker progress surfaces.

ConstructOS is already stronger than OMC in five other areas:

1. Persisted backend workflow state instead of local session files.
2. Plugin-backed policy enforcement and required checks.
3. Graph-grounded project context and evidence packs.
4. Chat-first project setup and starter orchestration.
5. Delivery workflow verification tied to real project artifacts.

The correct strategy is not "copy OMC". The correct strategy is "lift its execution ergonomics into ConstructOS's persisted architecture."

## Second-Pass Refinement

This second pass narrows the recommendation in three important ways:

1. The main weakness in ConstructOS is not the Team Mode policy core. It is the Team Mode operational layer around dispatch, visibility, and runtime state.
2. The safest high-value adoption path is to improve orchestration visibility, context composition, and cache/reuse behavior without changing the core CQRS/eventing/plugin model.
3. Task-focused UX should improve by showing runtime truth more clearly, not by introducing a new abstract orchestration surface.

The practical reading is:

- keep the current Team Mode plugin and required-check model
- keep the current delivery verification model
- keep the current graph/context architecture
- change how runtime state is assembled, exposed, cached, and explained

## Scope Of This Analysis

This document is based on a direct review of OMC implementation surfaces including:

- `AGENTS.md`
- `src/features/model-routing/router.ts`
- `src/features/task-decomposer/index.ts`
- `src/features/context-injector/collector.ts`
- `src/features/state-manager/index.ts`
- `src/features/verification/*`
- `src/hooks/project-memory/*`
- `src/hooks/learner/*`
- `src/hooks/rules-injector/*`
- `src/hooks/task-size-detector/index.ts`
- `src/hooks/omc-orchestrator/index.ts`
- `src/hooks/autopilot/pipeline.ts`
- `src/hooks/ralph/verifier.ts`
- `src/hooks/team-pipeline/*`
- `src/team/*`
- `src/hud/mission-board.ts`

It is also grounded against the current ConstructOS implementation, especially:

- `app/features/agents/service.py`
- `app/features/agents/executor.py`
- `app/features/agents/runner.py`
- `app/shared/context_frames.py`
- `app/shared/knowledge_graph.py`
- `app/shared/task_automation.py`
- `app/shared/team_mode_lifecycle.py`
- `app/shared/execution_gates.py`
- `app/features/project_skills/application.py`
- `app/plugins/team_mode/*`
- `app/frontend/src/components/projects/ProjectContextSnapshotPanel.tsx`

## Comparative Assessment

| Pattern family | OMC shape | ConstructOS today | Decision |
| --- | --- | --- | --- |
| Execution state | File-backed mode state, explicit phases, resumable loops | Persisted tasks, plugin policies, automation state, verification tools | Adopt pattern, reimplement on persisted DB-backed execution sessions |
| Task sizing | Small/medium/large pre-gate to avoid over-orchestration | No equivalent lightweight pre-gate at chat/task kickoff level | Adopt with structured classifier first, heuristics only for non-authoritative hints |
| Task decomposition | Parallel subtasks with ownership/conflict hints | Starter seeding exists; no generic decomposition artifact for runtime work | Adopt as planning artifact and kickoff aid |
| Context injection | Collector merges rules, memory, learned skills | Prompt builder already merges rules, skills, graph, policy | Refactor toward a first-class context registry instead of ad hoc prompt assembly |
| Learned skills | Extracted skill files with triggers and auto-injection | Project/workspace skills exist, but matching and auto-application are shallow | Adopt strongly by extending existing skill model |
| Verification | Shared verification protocol reused across modes | `verify_team_mode_workflow` and `verify_delivery_workflow` are strong but not persisted as user-facing runs | Adopt as persisted verification-run artifact and UI |
| Mission visibility | HUD and mission board expose worker/task progress | Context snapshot panel exists, but execution visibility is fragmented | Adopt via project execution board, not terminal HUD clone |
| Follow-up shortcuts | Approved-plan follow-up launch shortcuts | Setup and kickoff exist, but follow-up UX is still verbose | Adopt carefully using persisted launch readiness state |
| Governance hooks | Guardrails stop orchestrator from doing worker work directly | Plugin checks and task role semantics exist | Partially adopt where it improves chat/runtime boundaries |
| tmux/CLI team runtime | Real worker panes and local session files | Server-side automation runner and MCP tools | Do not copy directly |

## Team Mode: What Stays And What Changes

### What Should Stay

These parts of ConstructOS Team Mode are directionally correct and should remain the core:

- plugin-backed Team Mode config and compiled policy
- required-check verification model
- semantic status mapping
- delivery verification and evidence contracts
- task-centric lifecycle model rather than separate pseudo-ticket systems

These are stronger than OMC's local orchestration model because they are persisted, policy-backed, and integrated with delivery contracts.

### What Should Change

The weak points are in the operational layer:

1. Team Mode runtime state is fragmented across:
   - task automation state
   - verification outputs
   - kickoff logic
   - execution gates
   - workflow communication events
2. Dispatch is deterministic but still too opaque for users and operators.
3. Role derivation is functional but still relies on layered fallback rules that are harder to reason about than a visible runtime snapshot.
4. Verification is stronger than execution visibility, which means users see "is it valid?" better than "what is happening right now?"
5. The UX is still plugin- and checks-centric in places where it should be task- and handoff-centric.

### OMC Patterns To Apply Specifically To Team Mode

From OMC, the useful Team-related ideas are:

- phase inference from live runtime state
- stable worker identity and canonicalization
- explicit monitor snapshots
- blocked-reason surfacing
- recent activity summaries
- clear distinction between planning, executing, fixing, completed, and failed

What should not be copied:

- tmux pane runtime
- file-local worker mailboxes as the primary runtime source
- CLI-specific team session machinery

### Team Mode Adoption Rule

For ConstructOS, Team Mode should evolve into:

- the same persisted workflow core as today
- plus an explicit operational snapshot layer
- plus task-focused runtime UX

This means Team Mode should feel more legible and controllable without becoming a different architecture.

## What ConstructOS Should Reuse

### 1. Execution Modes As Explicit State Machines

OMC's best structural pattern is that "mode" is not just a prompt style. It has:

- explicit state files
- legal transitions
- resumability
- cancellation semantics
- fix-loop caps

ConstructOS already has parts of this in:

- task automation state
- Team Mode lifecycle semantics
- plugin required checks
- delivery verification

What is missing is one persisted execution-session object that unifies these signals into a single source of truth.

#### Decision

Add a persisted `execution_session` or `workflow_run` model for chat kickoffs, Team Mode runs, and delivery runs.

#### Reimplementation Shape

- Backend:
  - create `app/features/agents/execution_sessions.py` or equivalent bounded module
  - persist `mode`, `phase`, `started_at`, `updated_at`, `completed_at`, `resume_context`, `verification_state`, `artifacts`, `cancellation_state`
- Integrate with:
  - `app/features/agents/service.py`
  - `app/features/agents/runner.py`
  - `app/shared/team_mode_lifecycle.py`
  - `app/plugins/team_mode/service_orchestration.py`
- Frontend:
  - expose a run timeline and current phase
  - show why a run is blocked, waiting, or resumable

#### Why This Matters

Today ConstructOS can verify workflow correctness, but it does not yet present execution as a coherent persisted narrative. OMC does this well conceptually.

### 1A. Team Mode Needs An Operational Snapshot Before It Needs A Rewrite

This is the most important refinement from the second pass.

ConstructOS does not first need a Team Mode rewrite. It first needs a reliable operational snapshot that answers:

- which Team Mode tasks are runnable now
- which role owns each runnable task
- which slots are already busy
- which tasks are blocked by dependencies
- which tasks are blocked by missing evidence or handoff
- what the next dispatch wave would be
- why kickoff is waiting

#### Decision

Extend the existing project checks/verification surface with a Team Mode runtime snapshot.

#### Reimplementation Shape

- Keep `verify_team_mode_workflow(...)` as the structural policy verifier.
- Add a runtime-oriented snapshot derived from:
  - current non-archived project tasks
  - current automation states
  - Team Mode config agents
  - derived task roles
  - dispatch planning output
  - kickoff planning output
- Return this snapshot alongside existing verification data.

#### UX Goal

Present Team Mode from the user's perspective as:

- active work
- queued next work
- blocked work
- role capacity
- kickoff readiness

Not only as:

- config validity
- required checks

This is the safest high-value Team Mode improvement that does not disturb the core.

### 2. Lightweight Task Sizing Before Heavy Orchestration

OMC's `task-size-detector` exists for a good reason: not every request should trigger a full orchestrated pipeline.

ConstructOS currently has:

- strong setup orchestration
- strong workflow verification
- explicit execution intent classification

But it does not yet have a formal "keep this lightweight" gate.

#### Decision

Add a pre-kickoff execution sizing stage.

#### Reimplementation Shape

- Add a structured classifier prompt similar to `chat_intent_classifier.md` that returns:
  - `task_size`: `small | medium | large | unknown`
  - `decomposition_needed`
  - `workflow_recommendation`: `direct_chat | single_agent | team_mode`
  - `reason`
- Treat this as advisory for runtime selection, but persisted when kickoff happens.
- If classification is uncertain, return `unknown` and stay conservative.

#### Important Constraint

Do not port OMC's heuristic-only sizing as an authoritative decision path. In ConstructOS, use LLM structured classification first and keep heuristics only as non-blocking UI hints if needed.

### 3. Task Decomposition With Ownership And Conflict Forecasting

OMC's task decomposer is not valuable because it is perfect. It is valuable because it turns "parallelize this" into an artifact:

- components
- ownership
- shared files
- acceptance criteria
- verification hints

ConstructOS has starter seeding and Team Mode roles, but it lacks a generic decomposition artifact for runtime work.

#### Decision

Add a decomposition artifact that can be attached to kickoff-ready projects and larger tasks.

#### Reimplementation Shape

- Create a planner service that outputs:
  - workstreams
  - role ownership
  - expected touched entities
  - dependency ordering
  - verification obligations
- Store the result as:
  - a specification
  - or a linked note/artifact on the project
  - or a dedicated `execution_plan` record
- Use it to:
  - seed tasks
  - drive Team Mode routing
  - prevent mixed-origin backlogs

#### Best Fit In ConstructOS

This belongs closest to:

- `setup_project_orchestration(...)`
- kickoff preparation
- future "plan from existing backlog" tools

### 4. Skill Memory And Auto-Application

This is one of the clearest reuse opportunities.

OMC has:

- learned skill extraction
- trigger matching
- session injection
- project-level and user-level skill layering

ConstructOS already has:

- workspace skills
- project skills
- skill modes (`advisory`, `enforced`)
- trust levels

That means the hard product substrate already exists here.

#### Decision

Upgrade ConstructOS skills from "stored reusable guidance" to "retrievable and auto-applicable execution memory".

#### Reimplementation Shape

- Extend skill metadata with:
  - trigger phrases
  - tags
  - usage count
  - content hash
  - last matched timestamp
  - optional example scopes
- Add a resolver module, for example:
  - `app/features/project_skills/resolver.py`
- Resolver output should include:
  - matching skill ids
  - match score
  - why matched
  - whether applied as enforced or advisory
- Inject resolved skills into:
  - `get_project_chat_context`
  - full/resume prompt construction
  - task executor prompt assembly

#### Product Extension

Add "promote from successful run" flows:

- after successful delivery or verification pass
- after repeated manual reuse by users
- after reviewed import from existing markdown playbooks

This is one of the highest-leverage features in the whole comparison.

### 5. Verification As A Persisted Artifact, Not Just A Function Call

OMC treats verification as a reusable protocol with checks, evidence freshness, and final verdict.

ConstructOS already has better verification semantics than OMC:

- `verify_team_mode_workflow(...)`
- `verify_delivery_workflow(...)`
- required checks per plugin
- explicit gate definitions in `app/shared/execution_gates.py`

The missing part is packaging verification as a durable user-facing run record.

#### Decision

Persist verification runs and expose them in the UI.

#### Reimplementation Shape

- Add `verification_run` records with:
  - scope
  - source workflow run
  - checks snapshot
  - required checks snapshot
  - evidence snapshot
  - verdict
  - freshness timestamp
- Reuse existing verification functions as the evaluation engine.
- Show:
  - last successful verification
  - last failed verification
  - what changed since the last run
  - which checks are stale

#### Why This Is Better Than OMC

OMC proves the UX need. ConstructOS can implement it with stronger persisted evidence and policy linkage.

### 6. Project Execution Board Instead Of Terminal HUD Copying

OMC's HUD and mission board are useful because they make orchestration legible:

- what is running
- who owns what
- where it is blocked
- what finished

ConstructOS already has pieces of this information, but they are split across:

- task states
- automation states
- plugin checks
- context snapshot UI
- task drawer details

#### Decision

Add a first-class execution board to the web app.

#### Reimplementation Shape

Build a project-level panel that combines:

- active workflow runs
- Team Mode role slices
- current lifecycle phase
- required check failures
- latest evidence
- queued/running/completed automation counts
- "kickoff required" and "blocking state" summaries

#### Frontend Candidates

- new `ProjectExecutionBoard` component
- integrated with `ProjectsInlineEditor.tsx`
- possibly adjacent to `ProjectContextSnapshotPanel.tsx`

This should reuse ConstructOS data, not imitate OMC's terminal-specific HUD widgets.

### 6A. Execution UX Must Be Task-First, Not Plugin-First

This is the main UX constraint from the second pass.

The execution board and Team Mode views should be centered on:

- task title
- current owner role
- current automation state
- next runnable step
- blocker reason
- evidence/handoff state

The UI should not force the user to mentally reconstruct runtime status from:

- raw check IDs
- plugin config
- policy fragments

Plugin and policy detail still matters, but it should sit behind the task-level operational view.

### 7. Context Assembly Should Become A First-Class Runtime Layer

OMC's context collector and injection hooks are simple but effective. They reduce prompt construction to:

- register context
- prioritize context
- consume context

ConstructOS already does sophisticated prompt assembly, especially with:

- rules
- skills
- plugin policy
- graph context
- graph evidence
- delta frames

#### Decision

Refactor prompt assembly toward a context registry abstraction.

#### Reimplementation Shape

- Add a shared registry for prompt segments:
  - source id
  - priority
  - freshness
  - scope
  - token/char usage
- Make:
  - project rules
  - project skills
  - plugin required checks
  - graph context
  - graph evidence
  - delta frame
  - runtime metadata
  first-class registered segments
- Keep `full_prompt.md` and `resume_prompt.md` as render templates over the registry output, not as the only composition mechanism.

This is a refactor, not a new feature, but it will simplify future automation work.

### 7A. Adopt OMC's Context Discipline, Not Its Hook System

The second pass confirms that OMC is notably better at treating context as a managed runtime resource.

Useful ideas from OMC:

- register context by source
- prioritize context
- inject once per session/scope
- avoid duplicate context
- keep session-local caches bounded
- make compaction and freshness explicit concerns

ConstructOS already has some of this in separate places:

- `ContextSessionState`
- structured prompt cache in `codex_mcp_adapter.py`
- classification caches
- prompt segment accounting
- graph delta/full frame logic

What is missing is one explicit policy for context assembly and reuse across these mechanisms.

#### Decision

Introduce a unified context assembly policy and gradually consolidate duplicated cache logic under it.

#### Immediate Target Areas

- `app/shared/context_frames.py`
- `app/features/agents/codex_mcp_adapter.py`
- `app/features/agents/intent_classifier.py`
- `app/shared/classification_cache.py`

#### Architectural Goal

Context freshness, dedupe, and cache reuse should become intentional platform behavior rather than a collection of local optimizations.

### 7B. Cache The Expensive Parts, Not The Truth

Another strong OMC lesson is that cache should accelerate context work, not become the runtime truth.

ConstructOS should keep these distinctions strict:

- DB/project state is truth
- graph context pack is derived truth
- prompt payloads and classifier outputs are caches
- runtime snapshots are persisted products of current truth, not heuristics

This means:

- continue caching prompt templates and structured prompt payloads
- continue caching classification outputs
- improve revision-aware invalidation around context frames and prompt segments
- do not let cache state silently replace project/task/plugin truth

### 8. Approved Follow-Up Shortcuts After Planning And Setup

OMC has a smart pattern where a prior approved plan can enable short follow-up commands to launch execution.

ConstructOS already persists enough structured state to do something safer:

- setup profile
- plugin verification
- kickoff readiness
- execution intent classification

#### Decision

Add persisted launch-readiness state and safe follow-up actions.

#### Reimplementation Shape

- After successful setup or planning, persist:
  - recommended next action
  - required missing inputs
  - whether kickoff is safe
  - whether delivery verification is blocking
- Accept short follow-ups such as:
  - "kick it off"
  - "start execution"
  - "continue"
- Resolve them against persisted readiness, not text heuristics alone.

This improves chat UX without weakening policy enforcement.

## What ConstructOS Should Not Copy

### 1. File-Local State As The Primary Runtime Truth

OMC relies heavily on `.omc/state/*`. That is correct for a local CLI orchestrator and wrong for ConstructOS.

ConstructOS should keep DB-backed state as the primary truth and use ephemeral local files only as caches or runner-local internals.

### 2. tmux/Pane Runtime Assumptions

OMC's CLI worker runtime is product-specific. ConstructOS already has a different runtime model based on:

- MCP tools
- provider execution
- background runner
- task workdirs
- delivery evidence

Do not port tmux worker management.

### 3. Keyword-Driven Authoritative Workflow Routing

OMC uses keyword detection heavily. ConstructOS already has a safer direction with structured classification prompts.

Do not make workflow-critical decisions from magic keywords alone.

### 4. Large Agent Catalog Surface

OMC exposes many agent roles and prompt surfaces. For ConstructOS this would likely create:

- policy drift
- runtime ambiguity
- a harder UX

ConstructOS should prefer a smaller set of product-aligned workflow roles and policy-backed execution paths.

### 5. Direct Import Of OMC Prompt/Hook Architecture

OMC is organized around local hook interception. ConstructOS is organized around persisted product entities, MCP surfaces, and service-layer policy.

Borrow the pattern, not the framework.

## Recommended Delivery Plan

### Phase 1: High-Leverage Additions

- Add Team Mode runtime snapshot to the existing project checks surface.
- Surface Team Mode runtime state in the project editor as a task-first operational view.
- Add skill auto-resolution and auto-application on top of current project/workspace skills.
- Add persisted verification runs using existing verification functions.
- Add pre-kickoff task sizing and workflow recommendation.
- Add a project execution board in the UI.

### Phase 2: Structural Refactors

- Introduce a prompt/context registry behind current prompt builders.
- Add persisted execution sessions with explicit phases and resumability.
- Add decomposition artifacts for large execution requests.

### Phase 3: UX Acceleration

- Add approved follow-up shortcuts based on persisted readiness state.
- Add skill promotion from successful runs.
- Add richer execution analytics and post-run summaries.

## Concrete Implementation Map

### Add

- `app/features/agents/team_mode_runtime.py`
- `app/features/project_skills/resolver.py`
- `app/features/agents/verification_runs.py`
- `app/features/agents/execution_sessions.py`
- `app/features/agents/task_sizing.py`
- `app/features/agents/task_decomposition.py`
- `app/frontend/src/components/projects/ProjectExecutionBoard.tsx`

### Extend

- `app/features/projects/api.py`
- `app/features/project_skills/application.py`
- `app/features/agents/service.py`
- `app/features/agents/executor.py`
- `app/features/agents/runner.py`
- `app/shared/context_frames.py`
- `app/frontend/src/components/projects/ProjectContextSnapshotPanel.tsx`

### Reuse As-Is

- plugin required-check model
- Team Mode lifecycle semantics
- delivery verification functions
- graph context pack and evidence ranking
- setup-project orchestration flow

## Priority Ranking

| Priority | Recommendation | Reason |
| --- | --- | --- |
| P0 | Team Mode runtime snapshot + task-first UI | Best improvement to current weak point without touching core workflow architecture |
| P0 | Skill auto-resolution and injection | Highest leverage, smallest conceptual gap, strongest existing substrate |
| P0 | Persisted verification runs | Immediate UX and operational value on top of existing checks |
| P0 | Project execution board | Makes runtime legible to users and operators |
| P1 | Task sizing classifier | Prevents unnecessary heavy orchestration |
| P1 | Execution session state machine | Unifies runtime narrative and recovery |
| P1 | Context registry refactor | Simplifies prompt composition and future extensions |
| P2 | Task decomposition artifacts | High value, but depends on clearer execution-session model |
| P2 | Follow-up launch shortcuts | Good UX accelerator after state persistence is in place |

## Agent Checklist

- Do not frame this work as an OMC integration project.
- Prefer extending existing ConstructOS capabilities before adding new product surfaces.
- When implementing OMC-inspired behavior, bind it to persisted entities and plugin policy.
- Keep graph evidence, required checks, and delivery evidence as authoritative constraints.
- For ambiguous kickoff or workflow choices, use structured classification and safe-negative behavior.

## Final Decision

ConstructOS should treat OMC as a pattern library for agent orchestration UX.

We should aggressively reuse its ideas around:

- explicit execution phases
- Team Mode monitor snapshots
- verification loops
- reusable learned skills
- decomposition
- operator visibility
- context freshness and bounded cache discipline

We should not copy its:

- local file state model
- tmux runtime assumptions
- heuristic-first workflow routing
- broad agent taxonomy

The implementation target is a more legible, more reusable, and more recoverable ConstructOS runtime built on the architecture we already have.
