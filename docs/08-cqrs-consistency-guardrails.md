# 08 CQRS Consistency Guardrails

## Status
Accepted (effective from 2026-02-20).

## Context
The platform uses CQRS + event sourcing on the write side, but some write paths still perform direct SQL mutations in feature API/application/command layers.

That drift makes behavior harder to reason about and weakens auditability guarantees because not every write operation is represented as a domain event.

## Decision
1. Write-side business mutations must go through:
`API -> ApplicationService -> execute_command -> CommandHandler -> Aggregate -> AggregateEventRepository.persist(...)`.
2. Every feature with write commands must expose an aggregate class in `domain.py`.
3. Feature-layer direct SQL writes are disallowed in:
- `app/features/**/api.py`
- `app/features/**/application.py`
- `app/features/**/command_handlers.py`
4. Direct `append_event()` calls are disallowed in feature API/application/command layers; events must be emitted via aggregate instances.
5. The repository-level guardrail check is enforced by `scripts/check_cqrs_guardrails.py`.
6. Temporary exceptions are permitted only through `scripts/cqrs_guardrails_allowlist.json` with explicit rationale and scoped regex.

## Intended Exceptions
Direct writes are still acceptable in infrastructure concerns:
- Authentication/session storage (`AuthSession` lifecycle).
- Command idempotency log (`CommandExecution`).
- Projection/checkpoint/snapshot internals (`ProjectionCheckpoint`, `AggregateSnapshot`, projection rebuild paths).
- Bootstrap and schema migration code (`shared/bootstrap.py`).

These exceptions are outside feature write slices and are not targeted by the guardrail scanner.

## Current Transitional Allowlist
As of this decision, the allowlist intentionally permits transitional cases that are scheduled for follow-up refactoring:
- `app/features/users/api.py`: auth session lifecycle writes.

## Consequences
- New direct write bypasses in feature command surfaces fail CI.
- Existing transitional bypasses remain visible and explicit until removed.
- Refactoring can proceed incrementally with clear safety rails.
