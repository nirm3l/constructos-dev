# Team Mode Workflow Source of Truth

## Purpose
This document is the authoritative execution model for Team Mode + Git Delivery + Docker Compose.
It defines deterministic runtime behavior, hard gates, task-to-task communication, and the implementation plan required to make the flow reliable end-to-end.
The classification policy in this document also applies to adjacent workflow plugins and orchestration layers that influence Team Mode execution, especially Git Delivery and Docker Compose request interpretation.

## Non-negotiable Rules
- No heuristic fallback for workflow decisions.
- Hard runtime gates decide execution and state transitions.
- LLM classification is required for ambiguous workflow/intent recognition; string heuristics must not be the deciding path.
- LLM output is advisory for content generation, but structured LLM classification is authoritative for intent/workflow classification inputs to deterministic gates.
- Team Mode and Git Delivery are plugins; behavior is active only when plugin is enabled.
- Task dependency topology with explicit states and transitions is mandatory and must always be created.

## Classification Policy
- Use structured LLM classification for:
  - chat intent detection,
  - kickoff-vs-regular execution recognition,
  - setup-vs-execution disambiguation,
  - workflow role/capability classification when not already explicit in stored structured fields.
- Apply the same policy across Team Mode, Git Delivery, Docker Compose, and setup/orchestration request handling whenever runtime behavior would otherwise depend on prompt interpretation.
- Treat this as a project-wide orchestration rule, not a Team Mode-only exception. Any plugin or workflow path that interprets user intent from prompt text must use structured LLM classification instead of keyword or string-shape heuristics.
- Classification must be language-agnostic. Runtime behavior may not depend on exact wording, keyword presence, string prefix, or the language used in the prompt.
- If structured LLM classification is unavailable, invalid, or uncertain, return a safe negative/unknown outcome instead of guessing.
- Runtime gates, state transitions, merge/deploy checks, and QA handoff checks remain deterministic and must not depend on heuristic text parsing.
- Persist classifier outputs when they affect later execution so runner/runtime code does not need to re-derive them from free text.

## Classification Reuse and Caching Policy
- The primary architectural rule is: classify once at the highest relevant entry point, persist the normalized intent envelope, and propagate it downstream.
- Caching is an optimization layer, not the primary coordination mechanism between layers.
- If a request has already been classified and the structured result is available, downstream code must consume that result instead of reclassifying the same instruction.
- Reclassification is allowed only when there is genuinely new user input or a different instruction payload that has not yet been classified.
- LLM classification caching should be implemented as a reusable shared capability, not as ad hoc per-feature logic.
- The reusable cache layer should:
  - key by normalized instruction payload plus relevant scope (`workspace_id`, `project_id`, classifier version, schema version),
  - return only structured classifier outputs,
  - be safe to use across Team Mode, Git Delivery, Docker Compose, and general task automation intent paths,
  - fail closed when cache entries are missing, stale, malformed, or schema-incompatible.
- Cache hits may reduce cost and latency, but they do not replace persisted intent propagation.
- Avoid request-layer architectures that depend on multiple lower-level classifier calls merely because cache exists; duplicated classification should still be removed where possible.

## Extraction Boundary
- Heuristic extraction is allowed only for evidence parsing and deterministic artifact reading, not for user-intent or workflow classification.
- Allowed examples:
  - parsing commit SHA or task branch evidence from `external_refs`
  - parsing deploy ports, stack names, or health paths from already-produced notes, comments, or refs
  - detecting whether a deploy/QA artifact contains concrete verification text when the result is used as supplementary evidence
- Forbidden examples:
  - deciding whether the user requested kickoff, setup, deploy, Docker Compose, Git Delivery, or completion from prompt text using keywords or string shape
  - deciding workflow scope, execution mode, or task completion semantics from raw instruction text without structured LLM classification
- Allowed extraction heuristics must fail closed:
  - missing or ambiguous evidence means "not found" or "insufficient evidence"
  - they must not guess the user's requested workflow

## Stack Naming Clarification
- `constructos-app` is the Compose project name for the task-management application itself.
- `constructos-cp` is the Compose project name for the protected control-plane services.
- `constructos-ws-default` is the default Docker Compose project/stack used by the `docker_compose` plugin for user project runtimes deployed through the application.
- When this document says Lead must deploy with Docker Compose, the default runtime target for app-managed project deployments is `constructos-ws-default` unless the project's `docker_compose` plugin config explicitly overrides the stack.
- Do not treat `constructos-ws-default` as the application stack or control-plane stack; it is the managed runtime stack for deployed project workloads.

## 1:1 Runtime Flow (Expected Behavior)

### 1) Kickoff
- Kickoff queues **Lead task only**.
- No direct kickoff dispatch to Developer or QA tasks.
- Whether a request is a kickoff request must come from persisted structured classification, not instruction text parsing.
- Lead evaluates project context and open Team Mode tasks, then explicitly dispatches runnable Developer tasks.

### 2) Developer cycle
- Lead dispatches one or more Developer tasks (bounded by project parallel limit).
- Developer executes implementation on task branch `task/<task-id>/<step>`.
- Developer must produce valid execution outcome contract and git delivery evidence:
  - `files_changed` (non-empty)
  - `commit_sha`
  - `branch` (`task/...`)
  - `artifacts` (at least one object with `kind` and `ref`)
- If executor output omits `files_changed`, runtime may deterministically derive it from concrete task-branch/worktree git evidence; missing executor bookkeeping may not by itself invalidate real implementation work.
- Dirty or uncommitted worktree changes are not sufficient for Developer completion. Team Mode Developer success requires a real committed task-branch handoff:
  - a real `task/...` branch must exist,
  - the handoff `commit_sha` must match the current task-branch `HEAD`,
  - the task branch must differ from `main` at handoff time.
- Runtime may use a deterministic Developer handoff finalizer only as a narrow bookkeeping repair path when all of the following are true:
  - execution ran in the correct task worktree on the correct `task/...` branch,
  - non-trivial implementation files exist as dirty/uncommitted changes,
  - the branch is not yet ahead of `main`,
  - there is no failing validation state,
  - and the only missing step is the final git stage/commit handoff.
- This finalizer is allowed to create the missing task-branch commit so the handoff becomes real, but it may not manufacture success when implementation is missing, ambiguous, trivial-only, or failing validation.
- If `git_delivery.execution.require_dev_tests=true`, Developer must return `tests_run=true` and `tests_passed=true`.
- If tests are reported as run, they may not be failing.
- On success, task transitions `Dev -> Lead`.

### 3) Lead integration + merge + deploy cycle
- Lead inspects completed Developer outputs.
- Lead merges ready Developer task branches into `main` deterministically.
- If a Lead task is currently `Blocked` and a Developer handoff later produces merge-ready output that satisfies the Lead task's dependency topology, runtime must deterministically rearm that Lead task by transitioning `Blocked -> Lead` before dispatch. This re-entry may not wait for the recurring Lead schedule.
- If Docker Compose plugin is enabled and `docker-compose.yml` is missing, Lead must create it from actual repository contents, commit it on a task branch, and merge that branch to `main`.
- Lead decides deploy readiness and prepares deterministic deploy assets, but managed Team Mode deploy execution is runner-controlled. Lead must not invoke `docker compose` manually from the task environment for managed Team Mode deploys.
- Runner performs deploy (`docker compose`) against the runtime stack defined by the `docker_compose` plugin config. The default app-managed runtime stack is `constructos-ws-default`, not `constructos-app`.
- Lead performs runtime health check (`/health` with configured port) against that same runtime stack.
- Lead writes structured deploy evidence to `external_refs`.
- `external_refs` may record deploy attempts, manifest paths, runtime decisions, and probe results, but they may not claim successful deploy/health prematurely. A successful deploy cycle requires explicit health success evidence (HTTP 200) consistent with the structured deploy snapshot.

### 4) Lead -> QA handoff (without status-change dependency)
- Lead emits explicit handoff signal to QA using:
  - `last_lead_handoff_token` (new unique token)
  - `last_lead_handoff_at`
  - `last_lead_handoff_deploy_execution`
  - references to required Dev/Lead evidence
- Lead explicitly queues QA via `TaskAutomationRequested`.
- QA is not unlocked by guesswork; QA preflight requires valid handoff token + required evidence for the current Lead deploy cycle.

### 5) QA cycle
- QA verifies minimum runtime availability (`health=200`) and required acceptance checks from specification/task scope.
- QA validates the runtime already deployed by the successful Lead cycle for the current handoff.
- QA must not invoke `docker compose`, rebuild, redeploy, or restart the managed runtime from the QA task environment during normal Team Mode validation.
- QA writes verifiable artifacts in `external_refs`.
- QA returns explicit PASS/FAIL.

### 6) Failure loop
- If QA fails, QA task transitions to `Blocked` with artifacted defect evidence.
- Lead is queued for triage and dispatches corrective Developer work.
- If Developer or QA corrective work resolves the previously blocking prerequisite, runtime must clear the stale blocked Lead cycle by rearming the Lead task to `Lead` and dispatching it through the normal handoff path.
- Cycle repeats until QA PASS.

### 7) Completion
- Project completion notification to human user is emitted only when all active project tasks are `Done` and blocking delivery gates are satisfied.
- Team Mode/project setup must ensure at least one human project-visible recipient exists for completion/blocker notifications. If a project has no human project member, runtime must fall back to a human workspace member instead of silently dropping notifications.

## Deterministic Communication Model

### Allowed inter-task signals
1. `TaskAutomationRequested` (explicit queue signal)
2. Status-change triggers (declarative rules)
3. Schedule triggers

### Policy decision
- For Lead -> QA, primary signal is explicit `TaskAutomationRequested` + handoff token.
- The dependency map remains mandatory through status-change trigger topology used for validation and knowledge graph extraction.
- Status-change trigger wiring remains as declarative topology and fallback, but is not the primary runtime orchestrator.
- Runtime must treat `TaskAutomationRequested` as authoritative when equivalent communication already exists for the same handoff edge/correlation window.
- Runtime must ignore or deduplicate equivalent status-change-trigger automation requests when the target task already has a matching direct `TaskAutomationRequested` communication for that handoff.
- Runtime must deduplicate equivalent signals so one handoff edge does not produce duplicate queue events.
- Runtime must still persist a distinct cross-task `TaskAutomationRequested` when the target task is already `queued` or `running`; it may coalesce only an exact duplicate active request, but it must not drop a new Lead/Developer/QA handoff simply because the receiver is busy.
- Every direct request should carry `source_task_id`, `reason`, `trigger_link`, and `correlation_id` for auditability and graph alignment.
- Task Flow should keep one edge per `(source_task_id, target_task_id)` pair and surface repeated communication as edge-level runtime history/timeline, not by multiplying duplicate edges.
- Task Flow runtime history should support drill-down to the concrete request/response pair for each recorded runtime event without inventing additional graph edges.
- If an upstream kickoff-to-Developer request loses direct provenance, runtime must normalize the source-less Team Mode Developer request from persisted Lead kickoff state instead of preserving it as generic `manual`.
- For `task_relationships.kind="depends_on"`, each relationship object is an alternative activation clause, not an implicit global `AND` across all `depends_on` entries. `match_mode` applies within one relationship object; runtime may rearm/dispatch the task when any declared `depends_on` clause is satisfied.

## Hard Gates (Authoritative)

### G1 Developer outcome contract gate
- Applies when task role is Developer and Git Delivery plugin is enabled.
- Required fields and schema must be valid.
- Fails if contract is missing/inconsistent.

### G2 Developer evidence gate
- Developer task may not complete without commit + task branch evidence in `external_refs`.

### G3 Lead merge gate
- Lead deploy phase may not proceed without at least one merge-ready Developer output.
- For Lead merge/deploy decisions, current repository state is authoritative over stale task commentary or legacy refs when they disagree.
- All Lead merge/deploy/runtime paths must use canonical repository path resolution for the current execution environment; container-local and host-docker path handling must not diverge across Lead code paths.

### G4 Lead deploy gate
- Lead must record deploy command evidence and health evidence.
- Runtime health gate (`runtime_deploy_health_ok`) must pass when configured as required.
- Closeout, QA handoff, and current-cycle validation may not infer successful deploy solely from loose `external_refs` titles or command markers. Structured deploy success requires an explicit deploy snapshot with a real execution timestamp, manifest path, command, target stack, health URL, and HTTP 200 result.
- Lead runtime paths must use canonical repository-path resolution consistently, regardless of whether code is running inside the app container or executing against the host Docker daemon.
- Managed Team Mode deploy execution must remain runner-controlled so Docker Compose executes from the canonical host-safe repository context. Prompt guidance may not require the Lead agent to run `docker compose` manually from inside the task container.
- Lead may prepare deterministic deploy assets and runtime-basis evidence, but may not block solely because runner-controlled deploy/health has not happened yet in the same Lead response cycle. Once prerequisites are ready, the runner owns deploy execution and post-deploy health gating.

### G5 QA handoff gate
- QA run is blocked unless:
  - `last_lead_handoff_token` exists,
  - handoff token freshness is valid,
  - `last_lead_handoff_deploy_execution.executed_at` matches the latest Lead deploy execution for the project,
  - Lead deploy evidence for current cycle exists.
- During a valid QA handoff cycle, the latest Lead deploy snapshot/current-cycle handoff is authoritative deployment context. QA may probe the runtime and record failures, but it may not treat a manual `docker compose` attempt from the QA task environment as valid validation evidence.

### G6 QA artifact gate
- QA PASS requires verifiable QA artifacts.

### G7 Completion gate
- Human completion notification emitted only after all active tasks reach `Done`.
- Human blocked/completion notifications may not be skipped merely because the project actor is an agent account; notification routing must resolve a human recipient from project membership first, then workspace membership as fallback.

## Ownership Matrix
- Developer: implementation + commit + branch evidence.
- Lead: sequencing, merge, compose synthesis (if missing), deploy, health, QA handoff.
- QA: runtime + acceptance validation, pass/fail evidence.
- Human: fallback owner when unrecoverable blocker occurs.

## Current Failure Modes to Eliminate
1. Lead/QA deadlock due to implicit handoff assumptions.
2. Developer passing with formal evidence but insufficient delivered scope.
3. Lead runs ending in "deferred" state without actionable phase progression.
4. Missing human blocker notifications for terminal stalls.
5. Overlap between verification checks and runtime gates causing operator confusion.
6. Kickoff/runtime behavior depending on string-shape heuristics instead of persisted structured intent classification.

## Implementation Plan

### Phase 1: Lead -> QA handoff contract (P0)
Changes:
- Add task fields:
  - `last_lead_handoff_token`
  - `last_lead_handoff_at`
  - `last_lead_handoff_refs_json`
- Add deterministic API/helper to emit handoff + queue QA.
- Update QA preflight gate to require handoff token and evidence refs.
- Include correlation metadata on queue request payload (`source_task_id`, `reason`, `trigger_link`, `correlation_id`).

Acceptance criteria:
- QA cannot run without token.
- Lead handoff emits token and queues QA in same transaction.
- QA starts without requiring status transition side effects.

### Phase 2: Lead phase state machine (P0)
Changes:
- Introduce explicit Lead phase progression in runner:
  - `triage -> merge -> deploy -> handoff_qa -> done | blocked`
- Move runtime health checks to deploy phase only.
- Remove ambiguous "deferred" terminal behavior.
- Replace free-text kickoff recognition in runner with persisted structured execution mode/classification from the request path.
- Replace all prompt-language-dependent execution branching with persisted structured classification from the request path.

Acceptance criteria:
- Lead run always exits with deterministic phase result.
- No circular wait between Lead deploy requirements and QA gating.
- Equivalent kickoff instructions with different wording behave identically because they use the same structured classification payload.
- Equivalent requests in different languages behave identically because they use the same structured classification payload.

### Phase 3: Developer scope integrity gate (P0)
Changes:
- Keep strict contract gate.
- Add deterministic scope integrity check tied to task instruction/spec acceptance markers.
- Enforce: if tests are run, they may not fail.

Acceptance criteria:
- README-only or non-scope commits cannot pass Developer completion gate.
- Developer completion consistently produces merge-ready outputs.

### Phase 4: Compose synthesis ownership (P0)
Changes:
- Lead deploy phase synthesizes `docker-compose.yml` when plugin enabled and manifest missing.
- Compose synthesis is generated from repository state and deploy target config, committed and merged deterministically.

Acceptance criteria:
- First deploy cycle succeeds without manual compose file creation.
- Deploy evidence and health evidence are always produced by Lead phase.

### Phase 5: Notifications and human handoff (P0)
Changes:
- Emit mandatory blocked notification (`agents.runner.workflow_blocked`) with structured payload:
  - `blocked_phase`, `blocking_gate_id`, `task_id`, `next_required_action`
- Keep dedupe on gate+task+phase.
- Preserve completion notification (`agents.runner.project_completed`).
- Human escalation may change the assignee, but it must preserve the task's `assigned_agent_code`
  so Team Mode role coverage remains intact after a blocked automation handoff.

Acceptance criteria:
- Every terminal block produces one visible human notification.
- Completion produces one deduped success notification.
- Human escalation never destroys Team Mode role coverage by clearing the task's Team Mode slot.

### Phase 6: Checks and gates cleanup (P1)
Changes:
- Keep runtime-authoritative checks only:
  - delivery: `repo_context_present`, `git_contract_ok`, `runtime_deploy_health_ok`
  - team mode: `role_coverage_present`, `required_topology_present`, `lead_oversight_not_done_before_delivery_complete`
- Remove dead/outdated check code paths (not only UI options).
- Expose execution gates state in project checks UI.
- Add workflow communication UI: explicit handoff timeline entries with source, target, reason, and dedupe state.

Acceptance criteria:
- No stale check identifiers in backend code.
- UI shows clear separation: runtime gates vs verification checks.

Current implementation note:
- Project checks API now exposes `workflow_communication` snapshot derived from task automation status fields (`last_requested_*`, handoff token/correlation metadata).
- Team Mode and Git Delivery project editor tabs render a compact communication view so operators can inspect who queued what, why, and with which correlation id.
- Backend check catalog is now explicitly scoped to core `team_mode` + `delivery` check sets (dynamic plugin check inheritance removed for this path).

### Phase 7: Prompt sharpening (P1)
Changes:
- Tighten existing Team Mode prompt templates:
  - Developer prompt: explicit outcome contract and evidence requirements.
  - Lead prompt: explicit merge+deploy+handoff steps.
  - QA prompt: explicit pass/fail artifact contract.
- Keep prompts short and deterministic; no heuristic language.
- Explicitly require structured LLM classification outputs to be written/preserved when setup + resource creation + kickoff are handled in one turn.

Acceptance criteria:
- New runs no longer fail on missing required contract fields.
- Lead no longer waits for QA evidence before deploy.
- Different phrasings of the same kickoff/setup request produce the same persisted execution intent and the same runtime behavior.

### Phase 8: E2E reliability suite (P0)
Required tests:
1. Happy path: setup -> kickoff -> Dev -> Lead merge/deploy -> QA pass -> completion notification.
2. Dev invalid evidence rejected.
3. Lead deploy failure emits blocked notification and actionable reason.
4. QA failure loops back to Dev with Lead triage.
5. Handoff token required for QA execution.

Acceptance criteria:
- Suite green in CI before release.

## Rollout Order
1. Phase 1
2. Phase 2
3. Phase 4
4. Phase 3
5. Phase 5
6. Phase 6
7. Phase 7
8. Phase 8

## Definition of Done for This Refactor
- Kickoff always starts with Lead only.
- Lead deterministically dispatches Developer work.
- Lead performs merge+deploy before QA unlock.
- QA unlock is deterministic via handoff token + explicit queue event.
- All terminal blocks notify human users.
- End-to-end Tetris prompt flow completes without manual intervention.
