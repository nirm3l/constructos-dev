# Pluginization Roadmap

## Goal
Reduce feature coupling in core services by moving optional workflow behavior into plugins.

This document tracks:
- what is already pluginized,
- where Team Mode still leaks into core,
- what to extract next,
- how to keep the plugin API reusable for non-Team-Mode plugins.

## Current Plugin Infrastructure

Implemented generic pieces:
- `app/plugins/base.py`
- `app/plugins/registry.py`
- `app/plugins/runner_policy.py`
- `app/plugins/executor_policy.py`
- `app/plugins/task_policy.py`
- `app/plugins/skill_policy.py`

Team Mode plugin currently provides:
- gate evaluation (`app/plugins/team_mode/gates.py`)
- runner role and kickoff semantics (`app/plugins/team_mode/runner.py`)
- executor task-scoped context/worktree policies (`app/plugins/team_mode/executor_policy.py`)
- service done-transition policy (`app/plugins/team_mode/service_policy.py`)
- skill contract (`app/plugins/team_mode/skill_contract.py`)
- workspace skill seed and kickoff prompt templates under plugin folders.

## Team Mode Leakage Map (Remaining Core Coupling)

### 1) `app/features/agents/service.py`
Still contains Team Mode-specific orchestration paths:
- `verify_team_mode_workflow(...)`
- `ensure_team_mode_project(...)`
- `_enforce_team_mode_done_transition(...)` wrappers and direct call sites
- Team Mode specific checks merged into global verification output

Why this leaks:
- core service owns Team Mode lifecycle and contract details instead of dispatching to plugin capabilities.

Target extraction:
- move Team Mode orchestration flows to plugin service module and invoke through plugin hooks.
Status:
- Partial: direct `plugins.team_mode.service_policy` import is removed, replaced by generic `plugins/service_policy.py` dispatcher.
- Partial+: `verify_team_mode_workflow` and `ensure_team_mode_project` now dispatch through generic plugin service hooks with core callback fallback.
- Done for orchestration extraction: `verify` and `ensure` implementation bodies are moved into `app/plugins/team_mode/service_orchestration.py`; core callbacks are now thin delegators.
- Remaining: remove callback fallback path after introducing second workflow plugin, then make plugin ownership mandatory for workflow-specific orchestration.

### 2) `app/features/agents/api.py`
Still contains Team Mode-specific kickoff path:
- `_maybe_dispatch_team_mode_kickoff(...)`
- prompt selection and kickoff-event shaping for Team Mode

Why this leaks:
- chat endpoint has embedded Team Mode intent handling instead of generic plugin kickoff dispatch.

Target extraction:
- replace with generic `plugin_api_policy.maybe_dispatch_execution_kickoff(...)`.
Status:
- Partial: generic API kickoff dispatcher (`app/plugins/api_policy.py`) is in place and wired first in chat paths.
- Done for kickoff dispatch path: Team Mode kickoff implementation moved to `app/plugins/team_mode/api_kickoff.py`, and chat entrypoints dispatch through plugin API policy.
- Done: shared full/resume prompt templates now use plugin guidance placeholder; Team Mode-specific workflow guidance moved into `app/plugins/team_mode/prompt_templates/*_workflow_guidance.md`.

### 3) `app/features/agents/runner.py`
Still has Team Mode-specific skill checks and branching:
- direct `TEAM_MODE_SKILL_KEY` import
- `_project_has_team_mode_skill(...)` helper
- Team Mode-specific schedule guard comment/logic in `queue_due_scheduled_tasks_once(...)`
- Team Mode-specific error strings and notification kind labels

Why this leaks:
- queue/runner engine should be generic and plugin-agnostic.

Target extraction:
- keep queue engine in core, move Team Mode conditions to runner-policy hooks:
  - schedule eligibility guard
  - success-evidence requirements
  - escalation notification shape.
Status:
- Partial: removed direct Team Mode skill-key checks from runner preflight and schedule guard path.
- Done for escalation payload labels: blocker notification payload now comes from plugin hook.
- Done for lead-outcome normalization: kickoff/recurring lead completion rewrites now come from plugin hook.
- Remaining: git-delivery evidence-failure wording and checks in runner success path are still core-level and should move to a delivery-focused plugin hook.

### 4) `app/features/agents/executor.py`
Still directly references Team Mode skill key and naming:
- `TEAM_MODE_SKILL_KEY` imports and variables like `project_team_mode_enabled`, `team_mode_enabled`

Why this leaks:
- task execution context should depend on plugin policy decisions, not Team Mode constants.

Target extraction:
- introduce generic capability booleans (for example `workflow_plugin_enabled`, `task_scoped_context_enabled`) based on plugin policy and selected skills.
Status:
- Partial: removed direct Team Mode skill-key dependency in executor path; workflow plugin activation now resolves from enabled plugin keys.
- Remaining: rename compatibility variables (`team_mode_enabled`) to plugin-generic names in context payloads once downstream prompt/adapter consumers are updated.

### 5) `app/features/tasks/command_handlers.py`
Still has Team Mode-specific worktree cleanup function:
- `_maybe_cleanup_team_mode_developer_worktree(...)`

Why this leaks:
- cleanup policy belongs to plugin/task policy, not task command handlers.

Target extraction:
- generic `_maybe_cleanup_plugin_worktree(...)` that uses `plugins.task_policy.should_cleanup_task_worktree(...)` only.
Status:
- Done for cleanup hook naming/dispatch: moved from Team Mode-specific helper to generic plugin helper.

### 6) Prompt templates in shared path
Some Team Mode instructions remain in shared codex templates:
- `app/shared/prompt_templates/codex/full_prompt.md`
- `app/shared/prompt_templates/codex/resume_prompt.md`

Why this leaks:
- Team Mode guidance in global templates increases coupling and accidental behavior.

Target extraction:
- keep global template neutral and append plugin-specific instruction fragments from enabled plugins.

## Reusable Plugin API Gaps

To make plugin mechanism truly reusable for future plugins, add these hook groups to `WorkflowPlugin` protocol.

### Runner hooks
- `runner_schedule_queue_guard(...) -> bool | None`
  - allow plugin to skip/allow a due schedule run.
- `runner_validate_completion(...) -> str | None`
  - return blocking error message when completion evidence is insufficient.
- `runner_blocker_notification_payload(...) -> dict`
  - plugin can shape escalation notification metadata.

### API hooks
- `api_maybe_dispatch_execution_kickoff(...) -> dict | None`
  - plugin controls kickoff dispatch behavior.

### Service hooks
- `service_verify_workflow(...) -> dict | None`
  - plugin can expose workflow verification under its gate scope.
- `service_ensure_project_contract(...) -> dict | None`
  - plugin-specific idempotent setup.
- `service_enforce_done_transition(...)`
  - plugin can block transitions until plugin workflow invariants hold.

### Task hooks
- `task_post_transition_cleanup(...)`
  - plugin-managed worktree cleanup and task-level side effects.

## Priority Order

1. Finish Team Mode isolation (remove all direct Team Mode references from core paths above).
2. Split `git_delivery` behavior into its own plugin (currently mixed via Team Mode + service checks).
Status:
- Done (core enforcement extraction): git-delivery preflight and commit-evidence success validation now run via `app/plugins/git_delivery/plugin.py` hooks.
- Done (skill seed isolation): `git_delivery` workspace skill seed moved to `app/plugins/git_delivery/workspace_skill_seeds/git_delivery.md`.
3. Move `github_delivery` orchestration to plugin.
Status:
- Done: `github_delivery` now has its own plugin module and plugin-local workspace skill seed.
- Done: Team Mode service orchestration delegates GitHub context attach/apply behavior to `app/plugins/github_delivery/service_orchestration.py`.
- Done: GitHub/repository context classifier moved out of `AgentTaskService` into `app/plugins/github_delivery/context_classifier.py`; service methods are delegators.
- Done: generic delivery-context classification hook surface added via `app/plugins/context_policy.py`, so service no longer directly imports provider plugin classifiers.
4. Move Event Storming worker/orchestration to plugin.
5. Move Knowledge Graph/RAG orchestration to plugin.

## Acceptance Criteria

Team Mode is considered isolated when:
- no `plugins.team_mode` imports remain in `app/features/**` except through generic plugin policy modules,
- no `TEAM_MODE_SKILL_KEY` references remain in core business logic,
- disabling Team Mode plugin removes Team Mode behavior without breaking core task/project flows,
- adding a second workflow plugin can reuse same hooks without changing core service code.
