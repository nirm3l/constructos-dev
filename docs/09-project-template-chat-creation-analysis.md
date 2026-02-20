# Project Template Feature Analysis and Chat-Driven Project Creation Proposal

## 1. Conclusion
Yes, it is both feasible and useful to introduce chat-driven interactive project creation:
- with templates, and
- without templates (manual setup).

The current architecture already provides most of the required building blocks.

## 2. What Is Already Working Well
- Template creation flow is implemented end-to-end:
  - create project,
  - bind template,
  - seed specifications/tasks/rules,
  - sync template graph scaffold.
  - See `app/features/project_templates/application.py`.
- MCP tools already expose template operations:
  - `list_project_templates`
  - `get_project_template`
  - `create_project_from_template`
  - See `app/features/agents/mcp_server.py`.
- Idempotency is already suitable for interactive chat retries:
  - fallback `command_id` generation in agent service,
  - replay behavior in command execution.
  - See `app/features/agents/service.py` and `app/shared/commanding.py`.
- Frontend already supports both modes:
  - manual project creation,
  - template-based project creation.
  - See `app/frontend/src/components/projects/ProjectsCreateForm.tsx` and `app/frontend/src/app/mutations/projectMutations.ts`.

## 3. Knowledge Graph Impact

### Positive impact
- Template projects enrich the graph with:
  - `Template` and `TemplateVersion` nodes,
  - template-specific scaffold nodes and edges,
  - project-template relations.
  - See `app/features/project_templates/graph_scaffold.py`.
- Retrieval is template-aware:
  - query expansion with template hints,
  - template alignment scoring in ranking,
  - template metadata included in search/context responses.
  - See `app/shared/knowledge_graph.py`.

### Current gaps and risks
- Graph projector currently does not handle `ProjectTemplateBound` directly.
  - Template scaffold currently relies on direct sync in template service.
  - See `app/shared/eventing_graph.py` and `app/features/project_templates/graph_scaffold.py`.
- `parameters` are persisted in template binding, but are not yet used for dynamic seed customization.
  - See `app/features/project_templates/schemas.py` and `app/features/project_templates/application.py`.

## 4. Should Chat Be Included in Project Creation?
Yes. It improves:
- usability (guided choices instead of large forms),
- consistency (template defaults and guardrails),
- speed (fewer manual setup steps),
- and onboarding for non-expert users.

It also aligns naturally with the existing MCP tool surface.

## 5. Recommended Approach

### Phase 1 (fastest ROI): Chat Orchestration on Existing APIs
Implement a guided chat flow using existing tools:
1. Ask goal and constraints.
2. Suggest template or manual mode.
3. Show template preview (`get_project_template`).
4. Confirm overrides (statuses, members, embedding settings).
5. Execute create call.
6. Offer immediate post-create tuning (optional).

No major backend refactor required.

### Phase 2: Add Preview/Dry-Run for Template Creation
Add a backend preview mode that returns:
- computed defaults,
- seed counts,
- planned entities,
- graph scaffold summary,
without creating records.

This is ideal for chat confirmation before mutation.

### Phase 3: Make `parameters` Operational
Use `parameters` to customize template seeds, for example:
- domain naming for DDD templates,
- device/profile targets for game templates,
- rule/task variants based on environment or team size.

## 6. Additional Technical Recommendation
Improve graph consistency by projecting template-binding-related graph updates through event projection as well (or by emitting a dedicated template scaffold event), to reduce reliance on direct, best-effort sync paths.

## 7. Final Recommendation
Proceed with chat-driven interactive creation now (Phase 1), then add preview mode and real parameterization in follow-up iterations. This gives immediate product value while keeping architecture changes incremental and safe.

