# Glossary

## Core Terms

- `Aggregate`: write-side domain object that validates commands and emits events.
- `Projection`: read-side representation built from events for query performance and UI delivery.
- `Command Handler`: application entry point that executes command intent against an aggregate.
- `Event Store`: append-only event stream storage (`kurrentdb` when enabled).
- `Read Model`: SQL materialized state used by APIs/UI.
- `Team Mode`: workflow orchestration model with role semantics (`Developer`, `QA`, `Lead`).
- `Setup Profile`: persisted starter/facet-driven project setup intent used during orchestration.
- `Plugin Config`: project plugin runtime configuration (for example Team Mode, Git Delivery, Docker Compose).
- `Source of Truth`: normative policy that defines expected behavior and constraints.

## Operational Terms

- `constructos-app`: fixed Compose project name for app stack runtime.
- `constructos-cp`: fixed Compose project name for control-plane runtime.
- `Protected services`: `license-control-plane` and `license-control-plane-backup`.
- `Local docs seed`: seeding internal docs from repository `docs/internal/*.md` when local deploy env flag is enabled.

## Agent Execution Terms

- `assigned_agent_code`: structured task routing slot for Team Mode/automation.
- `assignee_id`: concrete user/project-member assignment identifier.
- `execution_triggers`: structured task trigger configuration for automated execution.
- `delivery verification`: workflow checks validating git evidence, QA artifacts, and deploy evidence.
