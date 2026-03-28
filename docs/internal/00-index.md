# ConstructOS Internal Documentation Index

This folder is the internal technical documentation set for engineers and agents.

It is organized as a single reading path, with each document containing:

- `Normative Policy (Source of Truth)`
- `Implementation Reality`
- `Known Drift / Transitional Risk`
- `Agent Checklist`

## Recommended Reading Order

1. `00-index.md` (this file)
2. `01-architecture.md`
3. `02-domain-and-bounded-contexts.md`
4. `03-agent-runtime-and-automation.md`
5. `04-frontend-control-plane-and-ops.md`
6. `05-testing-and-quality.md`
7. `06-omc-patterns-and-adoption.md`
8. `99-glossary.md`

Use `90-policy-appendix.md` when you need full legacy policy details.

```mermaid
flowchart TD
  A[Start] --> B[01 Architecture]
  B --> C[02 Domain]
  C --> D[03 Agent Runtime]
  D --> E[04 Frontend and Ops]
  E --> F[05 Testing and Quality]
  F --> G[06 OMC Patterns and Adoption]
  G --> H[99 Glossary]
  D --> I[90 Policy Appendix when deep policy detail is needed]
```

## Document Ownership Map

| Area | Primary document | Integrated policy domain |
| --- | --- | --- |
| Runtime topology, CQRS/ES boundaries | `01-architecture.md` | CQRS/event-sourcing architecture policy |
| Domain aggregates, contexts, data model | `02-domain-and-bounded-contexts.md` | CQRS + Team Mode + Starters policy |
| Team Mode, setup orchestration, automation execution | `03-agent-runtime-and-automation.md` | Team Mode v2 + project setup orchestration policy |
| UI surfaces, control-plane boundary, deploy safety | `04-frontend-control-plane-and-ops.md` | Team Mode + testing policy |
| Test structure and enforcement | `05-testing-and-quality.md` | testing and quality policy |
| OMC-inspired adoption roadmap | `06-omc-patterns-and-adoption.md` | orchestration pattern adoption policy |

## Non-Negotiable Boundaries

- App stack Compose project name: `constructos-app`.
- Control-plane stack Compose project name: `constructos-cp`.
- `license-control-plane` and `license-control-plane-backup` are protected services.
- Do not run broad/unscoped Compose teardown commands that might affect both stacks.

## Fast Agent Start Checklist

- Load the target project context (`project rules`, `skills`, `plugin config`, `setup profile`) before changes.
- Confirm Team Mode and delivery workflow constraints before mutating workflow logic.
- Verify whether task scope is app stack only or touches control-plane surfaces.
- Treat policy sections as normative; treat implementation sections as current operational shape.

## Notes On Appendix

`90-policy-appendix.md` contains full legacy Source-of-Truth bodies preserved for traceability and deep reference. Operational work should start from documents `01` to `05` first, then consult the appendix only when needed.
