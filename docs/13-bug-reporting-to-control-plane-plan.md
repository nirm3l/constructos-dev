# 13 Bug Reporting From App to Control Plane Plan

Date: 2026-02-22

## 1) Goal

Provide a reliable and secure way for authenticated app users to submit bug reports from the product UI, store them in License Control Plane, and process them from a triage workflow.

## 2) Recommended Architecture (Best Option)

Use an authenticated server-to-server flow:

`App UI -> App API -> Control Plane API`

Why this is the best fit for this product:

- It matches your self-hosted model: app instances can still report to a central control plane without exposing public write endpoints from the browser.
- It reuses existing Control Plane installation auth patterns (`/v1/installations/*`) and app-side server config (`LICENSE_SERVER_URL`, `LICENSE_SERVER_TOKEN`).
- It keeps secrets out of browser code and enables better anti-spam controls.
- It allows local retry/outbox when Control Plane is temporarily unavailable.

## 3) Hard Policy (App UI)

For the product application UI, direct browser-to-Control-Plane API communication is forbidden.

Required routing pattern for app UI flows:

- `Browser UI -> application server -> Control Plane API`

This applies to bug reporting and any app-originated support flows that persist in Control Plane.
Marketing-site lead forms are intentionally out of scope for this policy and may use their own direct integration pattern.

## 4) Scope

In scope:

- In-app bug report form.
- App backend endpoint that validates and forwards bug reports.
- Control Plane persistence + admin listing/triage APIs.
- Delivery reliability with retry queue.
- Basic anti-abuse, dedup, and PII redaction.

Out of scope (phase 1):

- File attachments/screenshots.
- Automatic ticket creation in Jira/GitHub.
- Two-way comments back to app user.

## 5) Data Contract

### 5.1 App API contract (new)

`POST /api/support/bug-reports`

Request body (phase 1):

- `title` (required, max 140)
- `description` (required, max 4000)
- `steps_to_reproduce` (optional, max 4000)
- `expected_behavior` (optional, max 2000)
- `actual_behavior` (optional, max 2000)
- `severity` (required enum: `low|medium|high|critical`)
- `include_diagnostics` (boolean)
- `context` (optional object): `project_id`, `task_id`, `specification_id`, `route`, `tab`

Response:

- `ok`
- `report_id`
- `delivery_status` (`sent|queued`)
- `created_at`

### 5.2 Control Plane API contracts (new)

Public authenticated ingest:

- `POST /v1/support/bug-reports`
- Auth dependency: `_require_installation_auth`

Admin read/triage:

- `GET /v1/admin/bug-reports` (filters: `status`, `severity`, `workspace_id`, `customer_ref`, `q`)
- `PATCH /v1/admin/bug-reports/{report_id}` (fields: `status`, `triage_note`, `assignee`)

Suggested status enum:

- `new`, `triaged`, `in_progress`, `resolved`, `closed`, `rejected`

## 6) Data Model

### 6.1 Control Plane table (new)

`bug_reports`

Columns:

- `id` (int PK)
- `report_id` (uuid, unique)
- `installation_id` (indexed)
- `workspace_id` (indexed, nullable)
- `customer_ref` (indexed, nullable)
- `source` (`task-app` default)
- `status` (`new` default)
- `severity` (indexed)
- `title`
- `description`
- `steps_to_reproduce`
- `expected_behavior`
- `actual_behavior`
- `reporter_user_id` (nullable)
- `reporter_username` (nullable)
- `metadata_json` (diagnostics + context)
- `dedup_key` (indexed)
- `created_at`, `updated_at`

### 6.2 App-side outbox table (new)

`support_bug_report_outbox`

Columns:

- `id` (uuid PK)
- `payload_json`
- `dedup_key`
- `attempt_count`
- `next_attempt_at`
- `last_error`
- `sent_at` (nullable)
- `created_at`, `updated_at`

## 7) Reliability and Delivery

- If forward to Control Plane succeeds: return `delivery_status=sent`.
- If Control Plane is down/timeout: persist to outbox and return `delivery_status=queued`.
- Background worker flushes queue with exponential backoff (for example: 30s, 2m, 10m, 30m, 2h).
- Hard stop after configurable max attempts (for example 15), then keep item for manual inspection.

## 8) Security, Privacy, and Abuse Controls

- Validate all fields with strict length caps.
- Redact obvious secrets from free text before sending/storing (tokens, API keys, bearer headers).
- Store request IP and user-agent in metadata at Control Plane ingest.
- Add rate limiting at ingest per installation (for example 10/hour, 50/day) and optional per source IP (for public traffic).
- Dedup repeated submissions with normalized `dedup_key` over a short window (for example 24h).

## 9) UX Plan (App)

- Add `Report a Bug` action in a visible place (Profile panel and quick actions menu).
- Open modal/drawer with concise structured fields.
- Add checkbox `Include diagnostics` (default on) with explicit note about what is sent.
- Show submit result states: `Sent to support` and `Queued locally, will retry automatically`.
- Optional follow-up: add local list `My bug reports` with delivery state.

## 10) UX Plan (Control Plane)

Add a new `Bug Reports` section in Control Plane UI:

- table with filters (`status`, `severity`, `workspace`, `customer`, search)
- detail panel with report content + metadata JSON
- quick triage actions (`triaged`, `in_progress`, `resolved`, `closed`)

Keep this separate from `Contact Requests` for cleaner operator workflow.

## 11) Rollout Phases

### Phase 0: Remove or block direct browser calls

- Audit app browser code for direct calls to Control Plane endpoints.
- Replace direct calls with application-server proxy endpoints.
- Add CI guard (`rg`-based check) to block new direct Control Plane endpoint usage in app browser code.

### Phase 1: Control Plane backend

- Add model, serializer, ingest endpoint, admin list/patch endpoints.
- Add tests for validation, auth, dedup, list filters.

### Phase 2: App backend proxy + outbox

- Add `/api/support/bug-reports` endpoint.
- Add forwarder to Control Plane.
- Add outbox table + retry worker.
- Add tests for sent/queued flows.

### Phase 3: App frontend

- Add report modal and client API call.
- Add success/error/queued states.
- Add lightweight diagnostics collection.

### Phase 4: Control Plane frontend

- Add `Bug Reports` list and triage actions.
- Add filters and report details.

### Phase 5: Integrations (optional)

- Add optional webhook or connector to create Jira/GitHub issues from triaged reports.

## 12) Acceptance Criteria

- Authenticated user can submit bug report from app UI in under 10 seconds.
- Report is persisted in Control Plane and visible in admin UI.
- If Control Plane is unavailable, report is queued and eventually delivered automatically.
- Duplicate submissions within dedup window are merged or flagged.
- No plaintext sensitive tokens are stored after redaction.

## 13) Implementation Touchpoints

App backend:

- `app/features/support/api.py` (new)
- `app/features/support/service.py` (new)
- `app/shared/models.py` (outbox model)
- `app/shared/bootstrap.py` (schema guard)
- `app/main.py` (router include)

App frontend:

- `app/frontend/src/components/...` (new report modal/action)
- `app/frontend/src/api.ts` (new submit function)
- `app/frontend/src/types.ts` (request/response types)

Control Plane backend:

- `license_control_plane/main.py` (model + endpoints)
- `license_control_plane/tests/test_main.py` (new tests)

Control Plane frontend:

- `license_control_plane/frontend/src/api.ts`
- `license_control_plane/frontend/src/types.ts`
- `license_control_plane/frontend/src/App.tsx`

## 14) Default Configs (Suggested)

- `BUG_REPORT_MAX_BODY_CHARS=4000`
- `BUG_REPORT_RATE_LIMIT_PER_HOUR=10`
- `BUG_REPORT_RATE_LIMIT_PER_DAY=50`
- `BUG_REPORT_DEDUP_WINDOW_HOURS=24`
- `BUG_REPORT_OUTBOX_MAX_ATTEMPTS=15`

## 15) Notes for Self-Hosted Positioning

Your core app remains self-hosted-only. Bug reporting is a support telemetry channel to Control Plane and should be explicitly optional via config:

- `BUG_REPORTING_ENABLED=true|false`
- If disabled, hide the UI entry and skip backend route registration.
