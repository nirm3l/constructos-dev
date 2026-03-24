# Testing And Quality

## Normative Policy (Source of Truth)

- Backend canonical suite root is `app/tests/core/**`.
- New tests must be context-scoped and behavior-focused.
- Guardrails must prevent direct event append misuse and prohibited mutation patterns in feature modules.

## Implementation Reality

- Platform, agents, project, and work-item contexts are covered under `app/tests/core/contexts/*`.
- Shared runtime harnesses exist under `app/tests/core/support/*`.
- CQRS/eventing and command-id guardrails are actively enforced by tests.

## Known Drift / Transitional Risk

- Some legacy tests outside current canonical layout may still exist during migration windows.
- Runtime-dependent tests may require strict environment isolation to avoid flaky outcomes.

## Agent Checklist

- Add tests in the owning context folder, not in generic catch-all modules.
- Prefer regression-oriented assertions over fragile implementation details.
- Run at least the affected context tests plus policy guardrail tests when touching workflow core.

## Scope
This document defines the canonical testing strategy for the application backend.

Current canonical suite:
- `app/tests/core/**`
- Target size: `150-200` tests
- Current collected size: `198`

Any tests outside `app/tests/core/**` are out of policy unless explicitly approved for a temporary migration window.

## Objectives
- Keep CI feedback fast and stable.
- Maximize regression detection per test.
- Organize tests by bounded context, not by one large file.
- Prefer behavior-focused tests over implementation-detail tests.

## Canonical Test Layout
`app/tests/core` is the only active backend suite root.

Structure:
- `app/tests/core/contexts/agents/`
- `app/tests/core/contexts/projects/`
- `app/tests/core/contexts/work_items/`
- `app/tests/core/contexts/platform/`
- `app/tests/core/support/`

Rules:
- New tests must be placed in the correct bounded context folder.
- Do not create monolithic files.
- Keep each test module focused on one coherent behavior area.

## Test Admission Rules
A new test is accepted only if it protects one of the following:
- Critical business workflow behavior.
- Authorization or security boundary.
- Cross-module integration contract.
- Idempotency, dedupe, or replay safety behavior.
- A verified historical bug regression.

Default preference:
- Prefer adjusting existing tests over adding new tests.
- Add a new test only when behavior is genuinely new and cannot be covered by evolving an existing test in the same bounded context.

A new test should be rejected when it is:
- Pure duplication of existing behavior coverage.
- Asserting internal implementation details with low regression value.
- Trivial CRUD without a domain rule or integration contract.

## Quality Rules
- Use shared runtime helpers from `app/tests/core/support/`.
- Avoid copy/paste `build_client` setup blocks.
- Prefer deterministic setup and assertions.
- Use `monkeypatch` only when isolating external dependencies or non-deterministic boundaries.
- Name tests with behavior-first intent:
  - `test_<behavior>_<expected_outcome>`

## Size and Performance Budget
- Hard target range: `150-200` tests in default CI collection.
- If adding tests above `200`, remove/merge lower-value tests in the same PR.
- Keep runtime practical for local development and CI.

## Change Management Policy
When changing behavior:
1. Update or add tests in the matching bounded context.
2. Remove obsolete tests in the same area.
3. Keep total suite within the target range.
4. Prefer modifying an existing high-value test before introducing a new test file or case.

When fixing a production bug:
1. Add or adjust one regression test for that exact behavior.
2. Place it in the correct context folder.
3. Reference the bug/failure context in the PR description.

## Forbidden Patterns
- Adding new backend tests under `app/tests/test_*.py`.
- Reintroducing `app/tests/test_api.py`-style monoliths.
- Creating parallel suites outside `app/tests/core/**` without explicit approval.

## Execution Contract
Default pytest collection must remain pinned to:
- `app/tests/core` via `pyproject.toml`.

Recommended commands:
- `pytest`
- `pytest app/tests/core`

## PR Checklist (Testing)
- Test location is correct bounded context.
- Test has clear regression value.
- No low-value duplication.
- Suite size remains in `150-200`.
- `pytest` passes locally.
