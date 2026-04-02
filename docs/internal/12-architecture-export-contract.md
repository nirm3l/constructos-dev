# Architecture Export Contract

Date: 2026-04-02
Scope: runtime contract for generated architecture export surfaces used by Doctor, bootstrap consumers, and CI audit gates.

## Normative Policy (Source of Truth)

- `GET /api/debug/architecture-export` is the canonical runtime export surface.
- `/api/bootstrap` may include a compact mirror (`architecture_export_summary`) for boot-path compatibility, but should not become a second independently maintained schema.
- Contract enforcement must stay test-backed (`test_architecture_inventory.py`, `test_bootstrap_architecture_inventory_contract.py`) and CI-backed (`scripts/check_runtime_contracts.py` + runtime-contracts workflow).
- Descriptor/export drift must be treated as an operational signal, surfaced through Doctor runtime health and quick actions.

## Implementation Reality

The architecture export builder is implemented in:

- `app/features/architecture_inventory/export.py`

Primary API debug endpoint:

- `GET /api/debug/architecture-export`

Bootstrap compatibility mirror:

- `bootstrap.architecture_export_summary`
- `bootstrap.config.architecture_export_summary` (legacy mirror)

### Canonical Export Shape

`/api/debug/architecture-export` returns:

- `export_version: int`
- `generated_at: string (ISO UTC)`
- `inventory_generated_at: string | null`
- `counts: object`
  - `execution_providers: int`
  - `workflow_plugins: int`
  - `plugin_descriptors: int`
  - `constructos_mcp_tools: int`
  - `prompt_templates: int`
  - `bootstrap_startup_phases: int`
  - `bootstrap_shutdown_phases: int`
  - `internal_docs: int`
  - `internal_docs_reading_order: int`
- `execution_providers: array`
  - `provider: string`
  - `is_default: boolean`
  - `default_model: string | null`
  - `default_reasoning_effort: string | null`
- `workflow_plugins: array`
  - `key: string`
  - `check_scope: string | null`
  - `default_required_check_count: int`
  - `available_check_count: int`
- `plugin_descriptors: array`
  - `key: string`
  - `name: string`
  - `category: string`
  - `configurable: boolean`
  - `runtime_enabled: boolean`
  - `has_workflow_plugin_class: boolean`
  - `config_surface: string | null`
- `audit: object`
  - `ok: boolean`
  - `errors: string[]`
  - `warnings: string[]`

### Bootstrap Summary Shape

`bootstrap.architecture_export_summary` returns a compact mirror:

- `generated_at: string`
- `inventory_generated_at: string`
- `counts: object` (same keys as export counts)
- `plugin_descriptor_keys: string[]`
- `audit: object`
  - `ok: boolean`
  - `error_count: int`
  - `warning_count: int`
  - `errors: string[]`
  - `warnings: string[]`
- `cache_ttl_seconds: float`
- `cache_hit: boolean`
- `cache_status: object`
  - `key: string`
  - `has_payload: boolean`
  - `hit_count: int`
  - `miss_count: int`
  - `expires_in_seconds: float`

## Known Drift / Transitional Risk

- The debug export and bootstrap summary are intentionally different shapes (full vs compact); consumers must not assume identical field trees.
- Legacy bootstrap consumers may still read `bootstrap.config.*`; keep root + config mirror aligned until migration completes.
- Any descriptor seed/class mismatch can cause drift alerts even when core runtime is healthy; this is expected and should be actionable via Doctor quick actions.

## Agent Checklist

- If plugin descriptors or workflow plugin metadata change, run:
  - `python3 scripts/check_runtime_contracts.py`
  - `python3 -m pytest -q app/tests/core/contexts/platform/test_architecture_inventory.py app/tests/core/contexts/platform/test_bootstrap_architecture_inventory_contract.py app/tests/core/contexts/platform/test_doctor_api.py`
- If adding new export fields, update:
  - `app/features/architecture_inventory/export.py`
  - bootstrap summary mapper in `app/features/bootstrap/read_models.py`
  - contract tests above
  - this document and `docs/internal/00-index.md`
