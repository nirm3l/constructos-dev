# Plugin Config Control Plane Plan

## Objective
Move Team Mode, Git Delivery, and Docker Compose behavior from prompt/rule text into strict project plugin configuration enforced by MCP and server policy logic.

Chat setup remains supported, but chat only orchestrates MCP tool calls.

## Scope Assumption
This plan targets a recreate-from-zero rollout. Legacy migration compatibility is out of scope.

## Product Direction Update (Core-First UI)
This rollout now prioritizes a strict "core/basic" baseline:
- Most meaningful configuration must be exposed as structured UI controls.
- JSON editing remains available only as an advanced override, not primary setup UX.
- Non-essential fields are removed from default UI flows.
- Outdated or low-signal checks are removed from default required sets.
- New fields/checks are added later only when they prove operational value.

Core principle:
- Minimize policy surface first, then expand deliberately.

## Delivery Mode
Use clean-cut replacement, not compatibility layering.
- No requirement to keep fallback to old behavior during implementation.
- Legacy gate-policy/rule-driven paths can be removed incrementally as new policy paths land.
- Temporary non-functional intermediate states are acceptable during active development.
- Priority is architectural correctness and final consistency, not continuous backward operability.

## Architecture Analysis (Current State)
Current behavior is distributed across these seams:
- Plugin protocol and registry: `app/plugins/base.py`, `app/plugins/registry.py`
- Gate checks and policy parsing: `app/features/agents/gates.py`
- Team Mode checks and done-transition enforcement: `app/plugins/team_mode/gates.py`, `app/plugins/team_mode/service_policy.py`
- Workflow verification orchestration: `app/plugins/team_mode/service_orchestration.py`, `app/features/agents/service.py`
- MCP surface and chat prompt context: `app/features/agents/mcp_server.py`, `app/features/agents/codex_mcp_adapter.py`

Main architectural issue today:
- Gate policy is JSON in project rules and mixed with plugin checks.
- Enforcement logic is split between verifier paths and transition-time guards.
- Tool exposure is broad; plugin-disabled tools can still pollute model context.

## What "Gates" Should Become

`Gates` should evolve into a three-layer policy subsystem, not a renamed checklist.

### 1) Policy Compiler (Config-Time)
Runs on `validate/apply` for plugin config.
- Validates schema and cross-field invariants.
- Produces normalized policy snapshot for runtime.
- Rejects invalid policy before activation.

Example invariants:
- Status transition graph rules are valid.
- Role authority references existing project roles.
- Branch strategy and PR requirements are compatible.
- Docker compose protected services policy is consistent with safety constraints.

### 2) Policy Decision Point (Runtime Authorization)
Runs before every guarded action.
- Input: actor, action, project state, active plugin policy snapshot.
- Output: `allow|deny` + `reason_code` + structured metadata.
- No heuristic fallback for ambiguous classification; return deterministic `unknown/blocked`.

Guarded actions include:
- Task status transitions
- Assignment/handoff
- Merge/close decisions
- Runner execution steps
- Docker compose operations

### 3) Evidence Verifier (Runtime Quality Contract)
Runs at workflow checkpoints and closeout.
- Verifies artifact contracts: commits, PR links, test evidence, deploy evidence.
- Produces machine-readable pass/fail map used by decision point.

This replaces prompt-era "did we do enough" checks with typed evidence contracts.

## Target Data Model

Add project-scoped plugin config store:
- `project_plugin_configs`
- Key: `(workspace_id, project_id, plugin_key)`
- Fields:
  - `enabled` (bool)
  - `schema_version` (int)
  - `config_json` (json/text)
  - `compiled_policy_json` (json/text)
  - `compiled_at` (timestamp)
  - `updated_by`, `created_by`, timestamps

Add project capability snapshot (derived):
- `project_capabilities`
- Purpose: quick lookup for context/tool exposure
- Contains active plugin keys and operational capability flags

## Plugin Config Schemas (v1)

### Team Mode
- Team roster and role model
- Status model and allowed transitions
- Ownership matrix (who can assign, move, merge)
- Escalation and recurring oversight policy
- Evidence requirements per handoff stage

Core v1 UI fields:
- Team members (user + role)
- Allowed status transitions
- Merge authority role(s)
- Lead oversight interval

Defer from core UI (advanced only):
- Rare governance edge cases and non-critical tuning fields

### Git Delivery
- Repository identity and default branch
- Branching mode (`feature_branch`, `trunk`, `develop_main`)
- Branch naming constraints
- PR requirement and required checks
- Merge authority and strategy
- Commit evidence requirements

Core v1 UI fields:
- Enable/disable delivery contract
- Required checks (minimal curated set)

Defer from core UI (advanced only):
- Evaluation strategy toggles and niche policy knobs

### Docker Compose
- Workspace root and compose file set
- Compose project name
- Allowed commands
- Allowed/protected services
- Deploy health contract

Core v1 UI fields:
- Runtime health requirement toggle
- Runtime stack
- Runtime host/port/path
- HTTP 200 requirement

Defer from core UI (advanced only):
- Seldom-changed compose safety arrays unless needed for a concrete scenario

## MCP Contract

### Core Config Tools (Always Exposed)
- `get_project_plugin_config`
- `set_project_plugin_enabled`
- `validate_project_plugin_config`
- `apply_project_plugin_config`
- `diff_project_plugin_config`
- `get_project_capabilities`

### Operational Tools (Conditionally Exposed)
Operational plugin tools are visible to agent context only when plugin is enabled for the active project.

Rules:
- If plugin disabled: operational tools are excluded from context.
- Setup exception: plugin-specific validate/preview tools may be available before enablement.
- Execution tools (run/deploy/merge orchestration) remain hidden until enabled.

## Chat Contract
Chat remains a first-class UX for setup and updates.

Chat flow:
1. Collect user intent (team size, branch model, etc.).
2. Build draft plugin config.
3. Call `validate_project_plugin_config`.
4. If valid, call `apply_project_plugin_config`.
5. Optionally call policy compilation/materialization.
6. Return applied config summary and policy version.

Chat never writes rules/policy text directly.

## Context Loading Strategy

Implement capability-aware tool filtering at context assembly time:
- Resolve project and active plugins first.
- Build MCP tool allowlist from `project_capabilities`.
- Pass only allowed tools into codex context payload.

Integration points:
- Tool discovery/filtering layer near `mcp_registry` + chat context builders
- Prompt/context assembly in `codex_mcp_adapter`

Even if FastMCP declares a broad static tool set, the model-facing context must be filtered to enabled capabilities.

## Enforcement Placement (Code-Level)

### Compile-Time Enforcement
- New application service for plugin config validate/apply
- Produces compiled policy snapshot stored per plugin

### Runtime Enforcement
- Task status mutations (`tasks` command handlers/application)
- Agent service done-transition checks (`features/agents/service.py`)
- Runner preflight/success validation hooks (current plugin runner/service policies)
- Docker compose wrappers and deploy operations

### Verification Endpoints
Existing verification-style endpoints should consume compiled policy snapshots, not raw gate-policy rules.

## Rules/Skills Position After Refactor
- Skills become optional assistants for collecting config input.
- Rules remain descriptive/project guidance, not authority for enforcement.
- Authoritative behavior is plugin config + compiled policy only.

## Execution Plan (Recreate-From-Zero)

### Phase 0: Core Surface Reduction (New)
- Define minimal required checks for Team Mode and Git Delivery.
- Remove non-core defaults that create noise or false friction.
- Move advanced configuration behind expandable "Advanced JSON" sections in UI.
- Remove/defer confusing strategy switches from primary UI (for example multi-mode evaluation controls).
- Enforce strict config validation on accepted core fields.

### Phase 1: Policy Foundation
- Add `project_plugin_configs` and `project_capabilities` models.
- Implement schema registry and per-plugin validators.
- Implement policy compiler and compiled snapshot persistence.

### Phase 2: MCP Config APIs
- Add core config MCP tools (get/validate/apply/enable/diff/capabilities).
- Add optimistic concurrency (`expected_version`).
- Return structured validation errors and reason codes.

### Phase 3: Conditional Tool Exposure
- Implement project capability resolver for chat sessions.
- Filter plugin operational tools from model context when disabled.
- Keep setup validate/preview tools visible.

### Phase 4: Runtime PDP Integration
- Route status transitions, handoffs, merge permissions, and runner gating through decision point API.
- Remove direct gate-policy JSON reads in runtime paths.

### Phase 5: UI Sections
- Add Team Mode, Git Delivery, Docker Compose project sections.
- Draft -> validate -> apply UX with policy preview.
- Show effective permissions/transitions/evidence contracts.

## Acceptance Criteria
- Full setup from chat works via MCP validate/apply only.
- UI and chat produce identical effective policy for same inputs.
- Disabled plugins do not inject operational tools into model context.
- Runtime guarded actions always return deterministic allow/deny + reason code.
- No policy authority comes from free-text skill/rule content.
- Primary plugin setup flow is UI-driven without requiring manual JSON editing.
- Default required checks are concise, high-signal, and explainable to non-expert users.

## Testing Strategy
- Validator unit tests (schema + cross-field invariants)
- Policy compiler tests (input config -> normalized snapshot)
- Decision point tests for transitions/merge/handoff/deploy actions
- Evidence verifier tests for commit/QA/deploy contracts
- MCP tests for validate/apply/version conflicts
- Context tests ensuring conditional tool exposure by plugin enablement

## Immediate Build Order
1. Data model + validator + compiler for `team_mode`
2. MCP tools for `team_mode` config
3. Capability-based tool filtering in chat context
4. Runtime transition enforcement through new decision point
5. Repeat for `git_delivery` and `docker_compose`

## Implementation Status (Current)
- Completed: `ProjectPluginConfig` model + service API (`get/validate/apply/enable`) and MCP tool surface.
- Completed: Team-mode transition enforcement now reads plugin policy config.
- Completed: Delivery verification is sourced from compiled plugin policy, not gate-policy rule parsing.
- Completed: REST endpoints for UI plugin control:
  - `GET /api/projects/{project_id}/plugins/{plugin_key}`
  - `POST /api/projects/{project_id}/plugins/{plugin_key}/validate`
  - `POST /api/projects/{project_id}/plugins/{plugin_key}/apply`
  - `POST /api/projects/{project_id}/plugins/{plugin_key}/enabled`
- Completed: Project UI now has dedicated sections/tabs for `Team Mode`, `Git Delivery`, and `Docker Compose` with enable/validate/save flows.
- Completed: API coverage test added for plugin config endpoints.
- Completed: Native FastMCP startup-time conditional registration added for plugin operational tools based on `AGENT_ENABLED_PLUGINS`.
- Completed: Project-aware MCP server filtering added to chat/context assembly (`filter_mcp_servers_for_project_plugins`) so plugin-scoped servers can be excluded when plugin config is disabled.
- Completed: MCP core config/tooling surface now includes `get_project_capabilities` and `diff_project_plugin_config` in service, MCP, and REST API layers.
- Completed: Legacy `Gate Policy` authority path removed from `apply_project_skill` and rule write-path special handling. Skill apply no longer creates/updates Gate Policy rule.
- Completed: Runner orchestration now reads plugin enablement from `ProjectPluginConfig` (`team_mode`, `git_delivery`) instead of `ProjectSkill` rows and no longer depends on `Gate Policy` project-rule mode parsing.
- Completed: Project editor UI copy for verification tab aligned to plugin policy/check terminology (no “open gate policy rule” affordance).
- Pending: Per-project dynamic tool-level filtering inside a single FastMCP server process (requires runtime capability in FastMCP itself; no workaround planned).
- Completed: Legacy plugin contract naming (`GateEvaluationContext`, `gate_*`, `evaluate_gates`) migrated to `PolicyEvaluationContext`, `check_*`, and `evaluate_checks` across active plugin/runtime call paths.
- In progress: Rename/remove remaining legacy `gates` naming in backend modules (`agents/gates.py` internals/constants) and stale tests after downstream test adjustments.
- Completed: Verification endpoint renamed to `/api/projects/{id}/checks/verify` and frontend wired to the new surface.
- Completed: `AgentTaskService.verify_delivery_workflow` and Team Mode orchestration now consume `plugin_policy` naming on main evaluation path (with normalized output carrying `plugin_policy` fields).
- Completed: Project UI checks panel now prefers `plugin_policy`/`plugin_policy_source` fields from verification payload.
- Completed: Core policy helpers in `features/agents/gates.py` now use plugin-first naming (`DEFAULT_PLUGIN_POLICY`, `plugin_policy_required_checks`) and removed unused Gate Policy rule parser path.
- Completed: Team Mode prompt/seed guidance updated from Gate Policy rule management to `git_delivery` project plugin config workflow (`get/validate/apply_project_plugin_config`).
