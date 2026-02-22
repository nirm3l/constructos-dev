# Skills Integration Analysis and Implementation Plan

## 1. Goal
Introduce reusable "skills" (including externally sourced internet skills) so they can be:
- applied during project creation from templates,
- attached later to existing projects,
- and optionally enforced through project rules and agent behavior.

## 2. Current Architecture Fit
The current system already has strong primitives that map well to skills:

- Template seeding pipeline already exists:
  - static template definitions in `app/features/project_templates/catalog.py`
  - preview/create flow in `app/features/project_templates/application.py`
  - existing seeded entities are `specifications`, `tasks`, and `project rules`
- Project-template binding already exists:
  - persisted in `project_template_bindings` model (`app/shared/models.py`)
  - exposed to UI bootstrap in `app/features/bootstrap/read_models.py`
- Project rules are already durable and agent-visible:
  - CRUD + read models in `app/features/rules/*`
  - injected into Codex context (`ProjectRules.md`) in `app/features/agents/codex_mcp_adapter.py`
- Project rules already participate in retrieval:
  - vector indexing in `app/shared/vector_store.py`
  - knowledge graph projection in `app/shared/eventing_graph.py`

This means skills can be layered without redesigning core architecture.

## 3. Current Gaps
There is no first-class skill model yet:

- no persistent skill catalog or versioning model
- no project-to-skill bindings
- no template-to-skill defaults
- no import pipeline for external skill sources
- no MCP/API/UI surface for skill lifecycle
- no trust/safety classification for internet-provided skills

## 4. Recommended Product Model
Use a two-layer model:

1. `Skill Catalog` (reusable definitions, versioned)
2. `Project Skill Bindings` (what is active on each project)

Then keep `Project Rules` as the enforcement/behavior surface.

Practical interpretation:
- skills are reusable, structured assets
- active skills can "project" into project rules/tasks/spec hints
- agent prompt receives both explicit project rules and active skills context

This gives structure without breaking existing rule-based behavior.

## 5. Data Model Proposal

### 5.1 New entities
- `SkillDefinition`
  - `id`, `workspace_id` (nullable for global), `key`, `name`, `summary`
  - `source_type` (`builtin|github|url|local`)
  - `source_locator` (repo/url/path), `version`, `checksum`
  - `manifest_json` (normalized skill payload)
  - `trust_level` (`verified|reviewed|untrusted`)
  - `created_by`, `updated_by`, `is_deleted`
- `ProjectSkillBinding`
  - `id`, `workspace_id`, `project_id`, `skill_id`
  - `pinned_version`
  - `mode` (`advisory|enforced`)
  - `enabled`
  - `config_json` (project-specific overrides)
  - `created_by`, `updated_by`, `is_deleted`

### 5.2 Optional but useful
- `ProjectRule.generated_from_skill_id` and `generated_from_skill_version`
  - enables traceability when a skill generates or updates rules

## 6. API and MCP Surface Proposal

### 6.1 REST
- `GET /api/skills`
- `POST /api/skills/import`
- `GET /api/skills/{skill_id}`
- `PATCH /api/skills/{skill_id}`
- `POST /api/skills/{skill_id}/delete`
- `GET /api/project-skills?workspace_id=&project_id=`
- `POST /api/project-skills` (attach skill to project)
- `PATCH /api/project-skills/{binding_id}`
- `POST /api/project-skills/{binding_id}/delete`

### 6.2 MCP tools
- `list_skills`
- `import_skill`
- `attach_skill_to_project`
- `list_project_skills`
- `update_project_skill`
- `detach_skill_from_project`

This mirrors existing patterns in `app/features/agents/mcp_server.py`.

## 7. Template Integration Proposal
Extend template definitions to include skills:

- add `skills` collection in `ProjectTemplateDefinition` in `app/features/project_templates/catalog.py`
- include `skill_count` in template serialization and preview summaries
- in `create_project_from_template`:
  - bind template (existing behavior)
  - seed specs/tasks/rules (existing behavior)
  - attach default template skills (new behavior)
  - optionally materialize enforced skill rules

Also support non-template usage:
- skill attach flow should work for any existing project.

## 8. Agent Runtime Integration Proposal
Current agent context includes project description, rules, and graph evidence.

Add:
- `ProjectSkills.md` context section in `app/features/agents/codex_mcp_adapter.py`
- skill loading in `_load_project_context` in `app/features/agents/executor.py`

Priority policy for behavior:
1. explicit user instruction
2. system safety constraints
3. enforced skills
4. project rules
5. advisory skills

This avoids unexpected behavior overrides.

## 9. Knowledge Graph and Vector Integration
To make skills useful in GraphRAG and semantic retrieval:

- graph projection:
  - add `Skill` (and optionally `SkillVersion`) nodes in `app/shared/eventing_graph.py`
  - add relations: `IN_PROJECT`, `USES_SKILL`, optionally `SKILL_GENERATES_RULE`
- label normalization and scoring:
  - extend entity label map and ranking in `app/shared/knowledge_graph.py`
- vector indexing:
  - add `skill` support in `app/shared/vector_store.py` source extraction/indexability
  - include active skill text in retrieval candidates

## 10. External Skill Import Strategy (Internet Skills)
Use a strict ingestion pipeline:

1. Fetch
  - source adapters (`github`, `raw url`, optional local path)
  - enforce timeout and max payload size
2. Normalize
  - parse to canonical JSON schema (`key`, `name`, `version`, `instructions`, `rules`, `tags`, etc.)
3. Validate
  - required fields
  - deterministic key/version format
  - safe content checks (block clearly unsafe directives)
4. Classify
  - default imported skills as `untrusted` or `reviewed`
5. Approve
  - require explicit user/admin action before `enforced` mode

This is critical to avoid prompt injection from internet-origin skill content.

## 11. Rollout Plan

### Phase 1: Fastest Value (low risk)
- Treat skills as managed imports that generate project rules.
- Add import endpoint + rule generation metadata.
- Add "Attach skill by URL/repo" in project UI.
- No major graph changes yet.

Expected outcome:
- immediate ability to reuse internet skills,
- strong compatibility with current project rules flow.

### Phase 2: First-class Skill Entities
- Add `SkillDefinition` and `ProjectSkillBinding`.
- Add CRUD APIs + MCP tools.
- Add project-level list/manage UI.

Expected outcome:
- versioning, traceability, per-project enable/disable.

### Phase 3: Template-aware Skills
- Extend template catalog and preview/create responses with skill defaults.
- Auto-attach template skills on project create.

Expected outcome:
- skills become a first-class part of project templates.

### Phase 4: GraphRAG + Vector Upgrade
- Project skills into graph and vector index.
- Include skill evidence in context pack and search ranking.

Expected outcome:
- better agent grounding and discoverability.

### Phase 5: Sync/Marketplace Operations
- optional periodic upstream refresh checks
- diff and "update available" workflow
- approval gates before applying updates

Expected outcome:
- scalable long-term internet skill management.

## 12. Concrete Backend Touchpoints
- Templates:
  - `app/features/project_templates/catalog.py`
  - `app/features/project_templates/application.py`
  - `app/features/project_templates/schemas.py`
- Rules:
  - `app/features/rules/domain.py`
  - `app/features/rules/command_handlers.py`
  - `app/features/rules/read_models.py`
- Models/bootstrap:
  - `app/shared/models.py`
  - `app/shared/bootstrap.py`
  - `app/shared/eventing_rebuild.py`
- Agent/MCP:
  - `app/features/agents/service.py`
  - `app/features/agents/mcp_server.py`
  - `app/features/agents/executor.py`
  - `app/features/agents/codex_mcp_adapter.py`
- Retrieval:
  - `app/shared/eventing_graph.py`
  - `app/shared/vector_store.py`
  - `app/shared/knowledge_graph.py`

## 13. Frontend Touchpoints
- types + API client:
  - `app/frontend/src/types.ts`
  - `app/frontend/src/api.ts`
- create-project workflow:
  - `app/frontend/src/components/projects/ProjectsCreateForm.tsx`
  - `app/frontend/src/app/mutations/projectMutations.ts`
  - `app/frontend/src/app/useProjectState.ts`
- project management view:
  - `app/frontend/src/components/projects/ProjectsInlineEditor.tsx`

## 14. Recommendation
Best path is:
- start with a rule-backed skill import flow (Phase 1),
- then formalize skills as first-class entities (Phase 2+),
- and integrate with templates plus GraphRAG afterwards.

This sequence gives fast user value while preserving compatibility with the current event-sourced, rule-centric architecture.
