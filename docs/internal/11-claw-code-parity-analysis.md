# Claw Code Parity Analysis And ConstructOS Reimplementation Notes

Date: 2026-04-02
Scope: direct review of `/home/m4tr1x/claw-code-parity` to identify architecture patterns that can improve ConstructOS in a future reimplementation or hardening pass.

## Normative Policy (Source of Truth)

- ConstructOS should only adopt patterns from `claw-code-parity` when they strengthen our persisted, policy-aware, DB-backed architecture.
- Do not import Claw's file-local session model, shim-heavy porting layer, or CLI-local assumptions as ConstructOS source of truth.
- Prefer generated inventories and test-backed manifests over hand-maintained architecture reports whenever the source can be derived from code.
- Keep structured LLM classification and safe-negative outcomes for ambiguous workflow decisions; do not introduce heuristic control-path fallbacks.
- For reimplementation work, preserve ConstructOS strengths: CQRS/event sourcing, persisted workflow state, plugin policy enforcement, graph/vector context, and separate control-plane boundary.

## Executive Summary

`claw-code-parity` is not just one codebase. It is three layers working together:

1. A Python mirror/introspection workspace under `src/`.
2. A Rust runtime workspace under `rust/crates/`.
3. A reference-data and parity-measurement layer under `src/reference_data/` plus `PARITY.md`.

The Python layer is intentionally small and explicit. It turns architecture into inspectable artifacts such as `PortManifest`, `QueryEnginePort`, `BootstrapGraph`, `CommandGraph`, `ExecutionRegistry`, and `ParityAuditResult`. The Rust layer is the real runtime direction: `api`, `runtime`, `tools`, `plugins`, `commands`, `compat-harness`, `telemetry`, and the CLI binary are separated into clear crates. The reference-data layer makes subsystem breadth and drift visible.

The most useful Claw patterns for ConstructOS are not the local session files or the porting shims. The useful patterns are:

1. Generated architecture inventories.
2. Registry-first capability modeling.
3. Bootstrap plans exposed as data.
4. Contract/parity audit harnesses.
5. Provider-neutral execution session artifacts.
6. Manifest-backed plugin and tool metadata.
7. Strong package/crate boundary discipline for future reimplementation.

ConstructOS has already implemented part of the earlier OMC-inspired operational layer:

- `app/plugins/team_mode/runtime_snapshot.py`
- `app/plugins/team_mode/execution_sessions.py`
- `app/features/agents/mcp_registry.py`
- `docs/internal/09-omc-adoption-implementation-report.md`

So this document focuses on the next improvement layer: making ConstructOS more self-describing, auditable, and reimplementation-friendly.

## Implementation Status (ConstructOS, 2026-04-02)

The following recommendations from this analysis are now implemented in ConstructOS:

1. Generated architecture inventory and audit layer:
   - `app/features/architecture_inventory/build.py`
   - `app/features/architecture_inventory/audit.py`
   - `scripts/check_runtime_contracts.py`
2. Runtime visibility endpoints:
   - `GET /api/debug/architecture-inventory`
3. CI contract gate:
   - `.github/workflows/runtime-contracts.yml` runs `python scripts/check_runtime_contracts.py`
4. Bootstrap contract integration:
   - `/api/bootstrap` now includes `architecture_inventory_summary`
   - `bootstrap.config.architecture_inventory_summary` mirrors the same payload for compatibility

Current `architecture_inventory_summary` shape:

- `generated_at`
- `counts`
- `internal_docs`:
  - `existing_docs_count`
  - `reading_order_count`
  - `missing_from_reading_order_count`
  - `unreferenced_docs_count`
  - `missing_from_reading_order`
  - `unreferenced_docs`
- `audit`:
  - `ok`
  - `error_count`
  - `warning_count`
  - `errors`
  - `warnings`
- `cache_ttl_seconds`
- `cache_hit`
- `cache_status`

Bootstrap consumer migration note:

- Preferred field: `bootstrap.architecture_inventory_summary`
- Compatibility mirror: `bootstrap.config.architecture_inventory_summary`
- Existing consumers can switch to the root field without breaking during transition because both fields currently carry identical payloads.

## What Exists In `claw-code-parity`

### 1. Python Mirror And Introspection Layer

The Python tree currently contains 66 Python files. Its purpose is not to be a full production runtime. Its purpose is to make the ported surface legible and measurable.

Key files and roles:

- `src/port_manifest.py`
  - Builds a `PortManifest` from the live `src/` tree.
  - Counts Python files and top-level modules.
  - Renders a compact Markdown manifest.
- `src/commands.py`
  - Loads `commands_snapshot.json` into typed `PortingModule` entries.
  - Provides search, filtering, and a mirrored execution shim.
- `src/tools.py`
  - Mirrors the same pattern for tools.
  - Includes permission-context filtering before surfacing tools.
- `src/execution_registry.py`
  - Wraps mirrored commands and tools behind stable execution objects.
- `src/query_engine.py`
  - Builds `QueryEnginePort`, a small stateful runtime with session id, usage tracking, transcript compaction, structured output fallback, and persistence.
- `src/runtime.py`
  - Assembles context, setup, routing, history, stream events, and turn results into a single `RuntimeSession` artifact.
- `src/bootstrap_graph.py`
  - Turns startup into an explicit graph/stage list.
- `src/setup.py`
  - Turns environment setup and prefetch steps into a serializable `SetupReport`.
- `src/system_init.py`
  - Builds a concise runtime init payload from the loaded command and tool surfaces.
- `src/parity_audit.py`
  - Measures current Python workspace coverage against an archived upstream TypeScript snapshot.

This layer is effective because it turns architecture into data structures instead of leaving it implicit in code paths.

### 2. Reference-Data Layer

The repository contains 29 subsystem reference JSON files under `src/reference_data/subsystems/`, plus root-level snapshots such as:

- `src/reference_data/archive_surface_snapshot.json`
- `src/reference_data/commands_snapshot.json`
- `src/reference_data/tools_snapshot.json`

Those files are small but strategically important. They provide:

- a machine-readable map of subsystem breadth
- a stable input for manifest loaders
- a baseline for parity checks
- a lightweight architecture memory layer independent of the live runtime

This is stronger than prose-only documentation because the data is directly consumable by code.

### 3. Rust Runtime Workspace

The Rust workspace currently has 8 crates:

- `api`
- `commands`
- `compat-harness`
- `plugins`
- `runtime`
- `rusty-claude-cli`
- `telemetry`
- `tools`

The separation is sensible:

- `runtime` holds session, config, permissions, MCP, bootstrap, and runtime primitives.
- `api` handles provider client and transport behavior.
- `tools` holds the tool registry and tool execution layer.
- `commands` holds command registry and slash-command surfaces.
- `plugins` holds plugin manifest, lifecycle, and hook abstractions.
- `compat-harness` extracts manifests from the upstream system to keep parity measurable.
- `rusty-claude-cli` is the concrete terminal application.
- `telemetry` stays independent.

This is not just cleanup. It creates a future reimplementation shape where core runtime policy does not collapse into one monolith.

### 4. Compatibility Harness

The most interesting Rust-side pattern is `rust/crates/compat-harness/src/lib.rs`.

It does not hardcode architecture reports manually. It derives them from source surfaces:

- `extract_commands(...)`
- `extract_tools(...)`
- `extract_bootstrap_plan(...)`

That is the right instinct. Even though the implementation is string-based and somewhat brittle, the pattern is strong: architecture facts should be extracted or generated where possible.

### 5. Session Persistence As Runtime Artifact

`rust/crates/runtime/src/session.rs` models session persistence explicitly:

- versioned session schema
- message block types (`Text`, `ToolUse`, `ToolResult`)
- compaction metadata
- fork metadata
- persistence path tracking
- rotation and cleanup behavior

This is a useful pattern because it preserves a provider-neutral execution transcript instead of only final summaries.

### 6. Plugin Metadata Layer

`rust/crates/plugins/src/lib.rs` models plugins with explicit manifest data:

- metadata (`name`, `version`, `description`, `kind`)
- permissions
- hooks
- lifecycle hooks
- plugin tools
- plugin commands

`rust/crates/tools/src/lib.rs` then merges built-in and plugin tools in one registry, with name-conflict checks and permission mapping.

This gives the runtime a clear notion of what exists, what is enabled, and what can safely be executed.

## Important Reality Check: Document Drift Exists In Claw

One important finding is that Claw's documentation and current code are not perfectly aligned.

Examples:

- `PARITY.md` still describes plugin parity as largely absent in Rust.
- `rust/README.md` still marks hooks as "config only" and plugins/skills registry as planned.
- But the current Rust tree already contains `rust/crates/plugins/src/lib.rs` and `rust/crates/plugins/src/hooks.rs` with concrete plugin and hook machinery.

This matters for ConstructOS because it shows a real failure mode:

- hand-maintained architecture gap documents drift quickly
- parity reports without generation or tests become stale
- the architecture eventually becomes better than its own explanation layer

ConstructOS should adopt the pattern of machine-readable inventories and audit harnesses, but should avoid Claw's drift by generating or validating those artifacts.

## Comparison To ConstructOS Today

ConstructOS is already stronger than Claw in several core areas:

- persisted domain state and workflow truth
- CQRS/event-sourced write model
- plugin-backed policy evaluation
- graph/vector context integration
- chat-first setup orchestration
- delivery verification tied to real project evidence

ConstructOS is weaker in a different area:

- it is less self-describing at runtime than it should be
- architecture facts are spread across code, docs, prompt templates, MCP tools, and UI contracts
- there is no single generated architecture inventory for operators, agents, CI, and future reimplementation work

Some Claw-inspired operational work is already present in ConstructOS:

- runtime snapshot: `app/plugins/team_mode/runtime_snapshot.py`
- execution sessions: `app/plugins/team_mode/execution_sessions.py`
- persisted session model: `app/shared/models.py` (`TeamModeExecutionSession`)
- MCP registry cache/telemetry: `app/features/agents/mcp_registry.py`

So the remaining opportunity is not "copy Claw runtime behavior". The remaining opportunity is "make ConstructOS architecture legible and auditable with the same explicitness".

## Patterns Worth Reusing In ConstructOS

### 1. Generated Architecture Inventory

#### How Claw Does It

Claw has a lightweight but explicit inventory layer:

- `PortManifest` in `src/port_manifest.py`
- subsystem JSON files under `src/reference_data/subsystems/`
- command/tool snapshots in `src/reference_data/*.json`
- audit summaries in `src/parity_audit.py`

#### ConstructOS Today

ConstructOS has strong documentation and strong runtime features, but its architecture map is fragmented across:

- `docs/internal/*.md`
- `app/plugins/registry.py`
- `app/features/agents/mcp_registry.py`
- `app/features/agents/mcp_server.py`
- `app/shared/prompt_templates/`
- `app/shared/models.py`
- `app/main.py`

#### Recommendation

Add a generated inventory layer, for example:

- `app/features/architecture_inventory/build.py`
- `app/features/architecture_inventory/snapshots/*.json`
- `scripts/check_architecture_inventory.py`

The generated inventory should include at least:

- workflow plugins and provided checks
- MCP tool surface and schema fingerprints
- background workers and bootstrap phases
- execution providers and auth requirements
- prompt templates and placeholder contracts
- core aggregates/read models/projection workers
- internal docs index consistency

#### Why It Helps

This would give ConstructOS:

- a machine-readable architecture map
- a stable input for reimplementation work
- a better source for internal UI/debug panels
- a CI-visible drift detector

#### Important Constraint

Do not hand-maintain this inventory. Generate it or validate it against code.

### 2. Unified Capability Registry

#### How Claw Does It

Claw models the execution surface through registries:

- `src/commands.py`
- `src/tools.py`
- `src/execution_registry.py`
- `rust/crates/tools/src/lib.rs`
- `rust/crates/commands/src/lib.rs`

The runtime can answer a simple question: what exists right now, from which source, and under which permissions.

#### ConstructOS Today

ConstructOS has partial registries, but they are split by concern:

- workflow plugins: `app/plugins/registry.py`
- MCP servers: `app/features/agents/mcp_registry.py`
- command-id provider routing cache: `app/features/agents/command_runtime_registry.py`
- executor/provider behavior: `app/features/agents/executor.py`
- prompt guidance and checks: spread across plugins and prompt templates

#### Recommendation

Create a first-class capability registry, for example:

- `app/features/agents/capability_registry.py`

It should unify metadata for:

- execution providers
- MCP servers
- workflow plugins
- verification surfaces
- prompt classifiers
- runtime bootstrap/debug surfaces
- optional project-scoped capability filters

#### Why It Helps

This would let ConstructOS expose one consistent source for:

- bootstrap/debug payloads
- admin/runtime UI
- agent prompt assembly
- internal audits
- future reimplementation boundaries

#### Priority

P0 for architecture legibility, even if the first version is read-only metadata.

### 3. Bootstrap Plan As Data

#### How Claw Does It

Claw makes startup legible through explicit artifacts:

- `src/bootstrap_graph.py`
- `src/setup.py`
- `src/system_init.py`
- `rust/crates/runtime/src/bootstrap.rs`

Instead of treating startup as an opaque side effect, it turns it into phases and reports.

#### ConstructOS Today

ConstructOS startup is described in `docs/internal/01-architecture.md`, but the runtime truth is spread across startup code and cache telemetry. Operators still have to infer too much from implementation.

#### Recommendation

Add a structured bootstrap plan/read model, for example:

- `app/features/bootstrap/plan.py`
- `app/features/bootstrap/read_models.py` extension

Model phases such as:

- schema/bootstrap repairs
- license startup check
- persistent subscription ensure
- read-model projection workers
- graph/vector workers
- event-storming worker
- notifications worker
- automation runner startup

Expose:

- configured phases
- actual phase timings
- skipped/disabled phases
- health/error state per phase
- cache freshness of expensive bootstrap substructures

#### Why It Helps

This gives a future ConstructOS reimplementation a stable startup contract instead of a documentation-only description.

### 4. Contract And Parity Audit Harness

#### How Claw Does It

Claw treats parity as a first-class concern:

- `src/parity_audit.py`
- `rust/crates/compat-harness/src/lib.rs`

The exact implementation is simple, but the architectural idea is correct: compare the system you have with the surface you believe you have.

#### ConstructOS Today

ConstructOS has several places where drift can happen:

- MCP tool implementation vs exposed schema
- workflow plugin policy docs vs actual checks
- prompt templates vs code that renders them
- frontend types vs API payload shape
- internal docs index vs actual docs set
- execution/session state payloads vs UI expectations

#### Recommendation

Add a ConstructOS audit harness, for example:

- `scripts/check_runtime_contracts.py`
- `app/features/architecture_inventory/audit.py`

Audit targets should include:

- MCP tool names and JSON schema fingerprints
- plugin registry keys and required checks
- prompt template placeholders and renderer inputs
- frontend API type snapshots for critical runtime payloads
- internal docs index consistency
- bootstrap phase list consistency

#### Why It Helps

This is the highest-leverage pattern from Claw for ConstructOS.

It directly reduces:

- silent contract drift
- stale internal docs
- avoidable agent retries
- UI/backend mismatch regressions

#### Important Constraint

For ConstructOS, prefer structured Python introspection over source-text regex extraction where possible. Claw's `compat-harness` is pragmatic, but ConstructOS can do better because we own the codebase.

### 5. Provider-Neutral Automation Session Artifact

#### How Claw Does It

Claw's Rust session model captures:

- message roles
- tool-use blocks
- tool-result blocks
- compaction history
- fork metadata
- persistence lifecycle

#### ConstructOS Today

ConstructOS already has `TeamModeExecutionSession`, but it currently stores a run summary, phase history, queued tasks, and blocked reasons. It does not yet preserve a provider-neutral structured automation transcript as a first-class artifact.

Relevant current files:

- `app/shared/models.py`
- `app/plugins/team_mode/execution_sessions.py`
- `app/features/agents/executor.py`
- `app/features/agents/runner.py`

#### Recommendation

Extend the execution-session layer or add a sibling artifact, for example:

- `app/features/agents/automation_session_logs.py`
- `automation_session_log` table or JSON artifact store

Persist:

- provider/model/reasoning settings
- structured message/tool events
- compaction summaries
- resume/fork lineage
- verification/fix sub-events
- final outcome contract

#### Why It Helps

This would improve:

- resume reliability
- postmortem debugging
- provider migration portability
- UI replay/debug surfaces
- auditability of agent behavior

#### Important Constraint

Use DB-backed persistence, not file-local session files, as the source of truth.

### 6. Manifest-Backed Plugin And Tool Metadata

#### How Claw Does It

Claw's Rust plugin system models metadata explicitly:

- plugin identity and version
- permissions
- hooks
- lifecycle
- plugin tools
- plugin commands

The tool registry can then merge built-ins and plugin tools with conflict checks.

#### ConstructOS Today

ConstructOS workflow plugins are code-first and static:

- `app/plugins/base.py`
- `app/plugins/registry.py`

That is good for policy evaluation, but metadata is still too implicit. Skills already have `manifest_json`, which shows the direction.

#### Recommendation

Introduce a metadata layer for workflow plugins and runtime capabilities.

Do not move policy evaluation into loose JSON. Keep safety-critical behavior in Python. But add a manifest or typed metadata object for:

- key
- version
- display label
- provided checks
- dependent MCP servers
- UI sections
- setup inputs
- prompt-template fragments
- runtime surfaces contributed by the plugin

Possible shape:

- `app/plugins/manifests/*.json`
- or generated `PluginDescriptor` objects beside each plugin implementation

#### Why It Helps

This makes plugins easier to:

- render in the UI
- inventory in CI
- expose in agent prompts
- reason about during reimplementation

### 7. Stronger Package Boundary Discipline For Reimplementation

#### How Claw Does It

Claw's Rust workspace is not perfect, but the separation is directionally right:

- `runtime`
- `api`
- `tools`
- `commands`
- `plugins`
- `telemetry`
- `compat-harness`
- CLI binary

#### ConstructOS Today

ConstructOS already has bounded contexts, but the agent runtime still spans multiple directories with some cross-cutting logic spread across:

- `app/features/agents/*`
- `app/plugins/*`
- `app/shared/*`

#### Recommendation

For any major reimplementation, mirror this kind of boundary discipline. Whether it stays Python or gains a lower-level runtime component, keep clear ownership boundaries such as:

- `contracts`
- `runtime`
- `registry`
- `plugins`
- `verification`
- `telemetry`
- `bootstrap`
- `execution_logs`

#### Why It Helps

This reduces long-term coupling between:

- policy evaluation
- transport/MCP concerns
- task execution
- audit/inventory generation
- UI runtime exposure

## Patterns ConstructOS Should Not Copy

The Claw review also makes it clear what should not be copied.

### 1. File-Local State As Authority

Examples in Claw:

- `.port_sessions`
- local session persistence in runtime files

ConstructOS should keep SQL/event-backed persistence as authoritative.

### 2. Shim-Layer Duplication As Product Runtime

The Python mirror is useful as a porting and introspection layer, but ConstructOS should not create a second fake runtime surface that drifts from the real one.

If ConstructOS adopts manifests and inventories, they should be generated from the real runtime.

### 3. Heuristic Prompt Routing For Control Decisions

`src/runtime.py` scores command/tool matches using simple token overlap. That is fine for a demo harness, but it is not acceptable for authoritative workflow classification in ConstructOS.

ConstructOS should keep structured LLM classification and safe-negative behavior.

### 4. Manual Parity Documents Without Validation

`PARITY.md` and parts of `rust/README.md` already lag behind current code. ConstructOS should not repeat this pattern.

## Recommended ConstructOS Reimplementation Path

### Phase 1: Inventory And Audit

Add immediately:

- generated architecture inventory
- capability registry
- runtime contract/parity audit script
- internal docs index validation

Suggested files:

- `app/features/architecture_inventory/build.py`
- `app/features/agents/capability_registry.py`
- `scripts/check_runtime_contracts.py`

### Phase 2: Bootstrap And Session Artifacts

Add next:

- bootstrap plan/read model
- provider-neutral automation session logs
- richer execution-session serialization for UI/debugging

Suggested files:

- `app/features/bootstrap/plan.py`
- `app/features/agents/automation_session_logs.py`
- `app/features/agents/session_serializers.py`

### Phase 3: Metadata-Backed Extensibility

Add for reimplementation readiness:

- plugin descriptors/manifests
- generated MCP/plugin/prompt metadata surface
- UI/debug panels driven from the registry instead of scattered ad hoc payloads

Suggested files:

- `app/plugins/descriptors.py`
- `app/features/architecture_inventory/export.py`
- `app/features/agents/capability_registry.py` extensions

## Priority Matrix

| Priority | Pattern | Why it matters now |
| --- | --- | --- |
| P0 | Generated architecture inventory | Highest leverage against drift and reimplementation confusion |
| P0 | Contract/parity audit harness | Prevents silent backend/UI/MCP/prompt mismatch |
| P0 | Unified capability registry | Makes runtime surfaces explicit for agents, UI, and CI |
| P1 | Bootstrap plan as data | Improves startup diagnostics and runtime legibility |
| P1 | Provider-neutral automation session artifact | Improves resume, debugging, and auditability |
| P2 | Manifest-backed plugin metadata | Strong for long-term extensibility but not as urgent |
| P2 | Package/crate boundary reshaping | Best handled during broader reimplementation rather than incremental edits |

## Agent Checklist

- If a new MCP tool, prompt template, runtime phase, or plugin is added, update the generated inventory and rerun contract audits.
- If a UI surface depends on runtime state, prefer consuming the capability registry or generated inventory rather than introducing a new implicit payload contract.
- If execution-session behavior changes, keep summaries and structured transcript artifacts aligned.
- If internal docs describe a runtime contract, back that description with generation or tests where possible.

## Final Conclusion

The most valuable lesson from `claw-code-parity` is not its CLI behavior. It is its insistence on turning runtime shape into explicit artifacts.

ConstructOS already has the stronger product architecture. What it lacks is an equally strong architecture self-description layer.

If we apply the right Claw patterns, ConstructOS should become:

- easier to reason about
- easier to verify
- harder to let drift silently
- easier to reimplement without losing system shape

That is the correct adoption target.
