# Project Starters Source of Truth

## Status
- Authoritative for replacing the current `Project Templates` feature with `Project Starters`.
- This change removes legacy template APIs, UI, bindings, and seeded template catalog support.
- Backward compatibility is not required unless explicitly called out in an implementation task.
- The target UX is chat-first project setup with optional visual starter selection and structured one-shot extraction.

## Goal
Replace the current template-based project creation model with a chat-native `Project Starters` model that:
- fits the application's conversational setup experience,
- preserves fast one-shot setup from a single prompt,
- still supports guided follow-up questions when information is missing,
- allows projects to have one dominant setup path plus additional facets,
- keeps Team Mode and other delivery/runtime capabilities available for every starter,
- removes the product vocabulary and implementation footprint of `Project Templates`.

## Problem Statement
The current `Project Templates` feature does not fit the product direction:
- the term `template` implies a rigid seeded blueprint rather than an interactive setup path,
- the current UI places template choice in a create form instead of the application chat,
- templates are modeled as static seeded entities rather than conversational setup strategies,
- `Team Mode`, `Git Delivery`, and `Docker Compose` are not project archetypes and should not be modeled as starter choices,
- projects may combine multiple characteristics such as `DDD` and `Web Game`, which does not map cleanly to a single rigid template type.

## Core Decisions
- The user-facing concept is `Project Starters`.
- The current `Project Templates` feature is removed from backend, MCP tools, and UI.
- Project setup is chat-first.
- Chat must support both:
  - explicit starter selection from a picker,
  - implicit extraction from a freeform prompt.
- A project has exactly one `primary starter`.
- A project may also carry zero or more `facets`.
- Operational capabilities remain separate from starters:
  - `Team Mode`
  - `Git Delivery`
  - `Docker Compose`
- The system must not force a rigid one-question-at-a-time wizard when the user already provided enough information in one prompt.
- The system must ask only the next missing question when structured extraction does not produce enough setup input.

## User Experience Model

### Entry points
Project setup must be available through two complementary chat paths:
- `Starter picker`
- `Freeform setup prompt`

Both paths are first-class and may be used together in the same setup session.

### Starter picker
When no project is selected, the chat composer must expose `Start project setup`.

Selecting it must reveal a `Project Starter` chooser that shows all available starter options.

The chooser is:
- a convenience and clarity tool,
- not a mandatory wizard step,
- not a replacement for freeform setup prompts.

The chat must explicitly communicate:
- `Choose a starter or describe your project in one message.`

### Freeform setup prompt
Users must remain able to send a single natural-language setup request containing all or most project information.

Example:

```text
Create a DDD browser game called Atlas Arena with Team Mode enabled, Git Delivery enabled,
Docker Compose on port 8088, and event storming turned on.
```

The setup system must attempt to extract all available structured fields from such a prompt before asking anything else.

### Guided follow-up
If required setup inputs remain unresolved after extraction:
- the backend must return only the next missing question,
- the chat should ask one short follow-up question at a time,
- the system must never ask for fields that were already extracted with sufficient confidence.

## Starter Model

### Primary starter
Each project must have one `primary_starter_key`.

The primary starter determines:
- the initial setup framing,
- the first-pass question set,
- starter-specific defaults,
- the initial kickoff artifact shape,
- retrieval hints associated with the project setup profile.

The primary starter is not the complete truth about the project. It is the dominant setup lens.

### Facets
Projects may also include zero or more `facet_keys`.

Facets represent additional product or architecture characteristics that refine setup behavior.

Facets:
- extend the question flow,
- extend retrieval hints,
- may add extra seeded artifacts or rules,
- must not require introducing combinatorial starter variants.

Example:
- `primary_starter_key = web_game`
- `facet_keys = [ddd_system]`

This allows a project to be both a `Web Game` and a `DDD System` without inventing a special merged starter.

### Operational capabilities
The following are not starters and must not appear as starter options:
- `Team Mode`
- `Git Delivery`
- `Docker Compose`

They are cross-cutting project capabilities configured within the setup flow for any starter.

## Initial Starter Catalog
Phase 1 must ship with exactly these starters:
- `web_app`
- `api_service`
- `ddd_system`
- `web_game`
- `blank`

### `web_app`
Use for:
- SaaS products,
- dashboards,
- admin tools,
- portals,
- CRUD-heavy applications.

### `api_service`
Use for:
- APIs,
- backend services,
- workers,
- integration-heavy systems,
- platform services.

### `ddd_system`
Use for:
- bounded contexts,
- aggregates,
- commands,
- events,
- projections,
- event storming oriented delivery.

### `web_game`
Use for:
- browser games,
- touch-first interactive experiences,
- performance-sensitive browser apps,
- device-matrix QA,
- asset-pipeline-heavy frontends.

### `blank`
Use for:
- custom projects that should not start from an opinionated path.

## Initial Facet Catalog
Phase 1 must support starter-independent facet modeling.

Initial facets:
- `ddd_system`
- `web_game`
- `realtime`
- `mobile_first`
- `api_backend`

Notes:
- `ddd_system` and `web_game` may appear either as the primary starter or as a facet.
- Future facets may be added without changing the starter picker model.

## Setup Conversation Architecture

### High-level flow
Project setup in chat must use three layers:
- `Intent router`
- `Project setup extractor`
- `Setup orchestration`

### Intent router
The existing chat intent classifier remains the top-level router.

Its job is to answer:
- is this project setup,
- is this kickoff,
- is this execution resume,
- is this project knowledge lookup,
- is this something else.

It must not become the only mechanism for determining starter choice or detailed setup payload.

### Project setup extractor
A new structured LLM extraction step must parse freeform setup requests into a setup payload.

It must extract, when present:
- primary starter,
- facets,
- project name,
- short description,
- capability toggles,
- deploy/runtime hints,
- starter-specific setup fields,
- unresolved/missing fields,
- extraction confidence.

This extractor is the canonical path for one-shot setup understanding.

### Setup orchestration
`setup_project_orchestration` remains the deterministic execution layer.

It must:
- accept structured setup input,
- determine which required fields are still missing,
- return only the next missing question when setup is incomplete,
- apply starter defaults and capability defaults,
- create or update the project,
- configure plugins,
- create starter-derived artifacts,
- persist setup profile metadata,
- verify resulting project wiring where applicable.

## Classifier and Extractor Responsibilities

### Intent classifier
The current intent classifier should remain focused on request intent, not project archetype truth.

It may be minimally extended to support setup routing metadata such as:
- `starter_selection_needed`
- `setup_extraction_required`

It must not be overloaded with starter-specific setup extraction.

### Setup extractor
The new extractor must own project-setup field extraction from freeform text.

Suggested canonical outputs:
- `project_creation_intent`
- `primary_starter_key`
- `facet_keys`
- `name`
- `short_description`
- `enable_team_mode`
- `enable_git_delivery`
- `enable_docker_compose`
- `docker_port`
- `expected_event_storming_enabled`
- starter-specific fields object
- `confidence`
- `reason`
- `missing_inputs`

### Priority of setup inputs
Conflicts must resolve in this order:
1. explicit UI starter picker selection,
2. explicit values clearly stated by the user in chat,
3. extractor inference,
4. unresolved field requiring follow-up question.

If the user-selected starter conflicts with the prompt:
- the system must not silently override the explicit picker,
- the chat should ask for clarification if the contradiction is material.

## Starter Picker Requirements
- The starter chooser lives in the application chat, not only in the legacy create-project form.
- The chooser must display all starter options clearly.
- Selecting a starter should pre-bind `primary_starter_key` for the current setup flow.
- The chat input remains active after starter selection.
- The selected starter may influence the composer placeholder text and example prompts.
- The user must still be able to type additional details in freeform immediately after starter selection.

## Starter-Specific Setup Rules

### Common rules
Every starter must define:
- starter label,
- short positioning text,
- recommended use cases,
- starter-specific default statuses if needed,
- starter-specific retrieval hints,
- starter-specific question set,
- starter-specific artifact generation rules.

### `ddd_system` rules
Must support setup for:
- domain name,
- bounded context framing,
- commands and domain events,
- projections and read models,
- integration boundaries,
- event storming preference.

The current DDD template content should be migrated into starter artifacts or starter overlays instead of template definitions.

### `web_game` rules
Must support setup for:
- gameplay or interactive experience framing,
- target device and browser profile,
- performance budget,
- asset pipeline,
- deployment target for QA,
- mobile-first or desktop-first intent.

The current Mobile Browser Game template content should be migrated into starter artifacts or starter overlays instead of template definitions.

### `web_app` rules
Must support setup for:
- user type,
- auth needs,
- CRUD or workflow-heavy shape,
- optional backend/API needs,
- delivery/runtime preferences.

### `api_service` rules
Must support setup for:
- service purpose,
- external integrations,
- background processing,
- runtime/deploy shape,
- API and worker concerns.

### `blank` rules
Must be intentionally minimal and avoid opinionated artifact seeding.

## Artifact Generation Model
Project Starters replace template seeding with starter-driven bootstrap artifacts.

Allowed artifact categories:
- project metadata defaults,
- starter setup profile record,
- optional kickoff note,
- optional initial specifications,
- optional initial tasks,
- optional project rules,
- optional graph/bootstrap hints.

Artifact generation must be:
- starter-aware,
- facet-aware,
- capability-aware,
- deterministic after setup input resolution.

It must not depend on the legacy template catalog implementation.

## Retrieval and Knowledge Graph Model
Today the system uses `template_key` for template-aware ranking in project knowledge retrieval.

That behavior must be migrated, not dropped.

### Replacement model
Knowledge retrieval must use setup profile metadata instead of template binding metadata.

At minimum it must support:
- `primary_starter_key`
- `facet_keys`
- optional setup tags or retrieval hints derived from the chosen starter/facets

### Requirement
Removing `Project Templates` must not reduce retrieval quality for projects that used template-aligned ranking signals.

## Data Model Changes

### Remove
The following legacy concept must be removed:
- `ProjectTemplateBinding`

The following legacy fields and concepts must disappear from runtime behavior and UI:
- `template_key`
- `template_version`
- template alias normalization,
- template preview payloads,
- template catalog definitions,
- template binding badges in project list or editor views.

### Add
Introduce a project setup profile model.

Suggested canonical shape:

```json
{
  "project_id": "uuid",
  "workspace_id": "uuid",
  "primary_starter_key": "web_game",
  "facet_keys": ["ddd_system", "mobile_first"],
  "starter_version": "1",
  "resolved_inputs": {},
  "retrieval_hints": ["gameplay", "performance_budget", "commands", "domain_events"],
  "applied_by": "user-id",
  "applied_at": "timestamp"
}
```

Naming does not need to be exactly this, but it must represent a setup profile rather than a template binding.

## API Changes

### Remove
Remove legacy project template endpoints:
- list templates
- get template
- preview project from template
- create project from template

Remove corresponding MCP tools and descriptions.

### Add
Add starter-aware setup support through chat-oriented and API-oriented surfaces.

Required capabilities:
- list available project starters,
- optionally list available facets,
- extract setup payload from freeform setup prompt,
- orchestrate starter-driven project setup,
- read persisted project setup profile.

If a dedicated list endpoint is added for starter metadata, it must return starter picker data rather than template catalog data.

## Frontend Changes

### Remove from project creation UI
Remove from the legacy project create form:
- `Project template` select,
- template plan preview,
- template parameter JSON input,
- template-specific create flow branch,
- template-related badges and labels across project list/editor surfaces.

### Add to chat UI
Add a `Project Starter` chooser to the chat setup entry point.

Requirements:
- all starter options visible,
- clear indication that freeform setup is also supported,
- selected starter state visible in the composer/setup context,
- starter-specific prompt hints after selection,
- graceful handling when the freeform prompt implies extra facets.

### Keep in create flow
The legacy create-project form may remain as a manual creation path, but it must no longer expose project templates.

If later desired, the create form may optionally expose starter selection, but chat remains the primary source of truth.

## Backend Changes

### Remove feature slice
Remove the `project_templates` feature slice and all dependent catalog, preview, and create logic.

### Introduce starter orchestration support
Backend must gain:
- starter catalog definitions,
- setup extractor prompt and parsing,
- starter-aware orchestration logic,
- starter/facet-aware artifact generation,
- setup profile persistence,
- retrieval integration using setup profile metadata.

### Preserve deterministic enforcement
Even though setup uses LLM extraction, final orchestration must remain deterministic and schema-driven.

The backend must never guess with fallback heuristics when required setup fields remain ambiguous.

## Migration Rules
- Existing template code is removed, not kept as a long-lived compatibility layer.
- Existing seeded DDD and Mobile Browser Game template content must be migrated into starter-driven bootstrap assets.
- Existing projects with template bindings may be:
  - migrated to setup profiles if migration support is implemented,
  - or left unsupported if backward compatibility is explicitly declared out of scope for the rewrite.

The implementation branch must choose one migration strategy explicitly before rollout.

## Implementation Phases

### Phase 1: Source-of-truth implementation primitives
- introduce starter catalog definitions,
- introduce setup extractor schema and prompt,
- extend orchestration to accept starter-aware structured payloads,
- add setup profile persistence,
- migrate retrieval from template key usage to setup profile usage.

### Phase 2: Chat UX
- add starter picker to chat,
- integrate selected starter with extraction flow,
- update starter setup entry prompt,
- support explicit picker plus freeform prompt merging.

### Phase 3: Artifact generation
- migrate DDD and Web Game seeded assets into starter/facet-driven bootstrap generation,
- add starter-aware kickoff note/spec/task/rule generation,
- verify capability toggles still work for every starter.

### Phase 4: Remove legacy templates
- delete template APIs,
- delete MCP template tools,
- delete frontend template UI,
- delete template bindings and badges,
- delete template retrieval hooks,
- delete template tests and replace them with starter coverage.

## Testing Requirements

### Backend
Add or update tests for:
- intent router still recognizing project setup correctly,
- setup extractor correctly resolving one-shot setup prompts,
- explicit starter picker overriding inferred starter selection,
- conflict handling between picker and prompt,
- starter-aware orchestration asking only the next missing question,
- DDD starter bootstrap behavior,
- Web Game starter bootstrap behavior,
- mixed starter plus facet cases such as `web_game` plus `ddd_system`,
- retrieval behavior using setup profile metadata instead of template binding.

### Frontend
Add or update tests for:
- chat starter chooser rendering,
- starter selection state in chat,
- freeform prompt flow without starter selection,
- removal of legacy template UI,
- project surfaces no longer rendering template labels.

## Non-Goals
- Do not introduce combinatorial starter variants such as `ddd_web_game`.
- Do not model Team Mode as a starter.
- Do not force the user through a rigid wizard when structured extraction already resolved enough setup information.
- Do not retain `Project Templates` as a parallel product concept after rollout.

## Acceptance Criteria
- No user-facing `Project Template` language remains in the product.
- No backend `Project Template` API or MCP tool remains in active use.
- Chat offers a visible starter chooser with all starter options.
- Chat still supports one-shot freeform setup extraction from a single prompt.
- Chat asks only the next missing setup question when needed.
- A project can be modeled as one primary starter plus additional facets.
- Team Mode, Git Delivery, and Docker Compose remain available for every starter.
- DDD and Web Game flows remain fully supported in the new starter model.
- Retrieval no longer depends on template bindings and still has equivalent setup-aware ranking signals.
