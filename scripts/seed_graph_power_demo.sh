#!/usr/bin/env bash
set -euo pipefail

API_URL="${API_URL:-http://localhost:8080}"
ACTOR_USER_ID="${ACTOR_USER_ID:-00000000-0000-0000-0000-000000000001}"
WORKSPACE_ID="${WORKSPACE_ID:-}"
BOT_USER_ID="${BOT_USER_ID:-}"
PROJECT_NAME="${PROJECT_NAME:-GraphRAG Demo: OmniFlow Commerce Control Plane ($(date -u +%Y-%m-%dT%H:%MZ))}"
PROJECT_DESCRIPTION="${PROJECT_DESCRIPTION:-High-signal demo projekat za prikaz GraphRAG context pack vrijednosti tokom planiranja i kodiranja: payments, inventory, fulfillment, notifications i incident ops.}"
OUTPUT_ROOT="${OUTPUT_ROOT:-data/graph-power-demo}"
WAIT_SECONDS="${WAIT_SECONDS:-120}"
RETRY_MAX_ATTEMPTS="${RETRY_MAX_ATTEMPTS:-6}"
RETRY_SLEEP_SECONDS="${RETRY_SLEEP_SECONDS:-0.25}"

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Missing required command: ${cmd}" >&2
    exit 1
  fi
}

require_cmd curl
require_cmd jq

new_command_id() {
  printf "kg-power-demo-%s-%s-%s" "$(date +%s%N)" "$BASHPID" "$RANDOM"
}

api_get_as() {
  local user_id="$1"
  local path="$2"
  local attempt=0
  local output
  while true; do
    if output="$(curl -fsS -H "X-User-Id: ${user_id}" "${API_URL}${path}" 2>&1)"; then
      printf '%s' "${output}"
      return 0
    fi
    attempt="$((attempt + 1))"
    if [[ "${attempt}" -ge "${RETRY_MAX_ATTEMPTS}" ]]; then
      echo "${output}" >&2
      return 1
    fi
    sleep "${RETRY_SLEEP_SECONDS}"
  done
}

api_post_as() {
  local user_id="$1"
  local path="$2"
  local payload="$3"
  local command_id
  local attempt=0
  local output
  command_id="$(new_command_id)"
  while true; do
    if output="$(
      curl -fsS \
        -H "Content-Type: application/json" \
        -H "X-User-Id: ${user_id}" \
        -H "X-Command-Id: ${command_id}" \
        -X POST \
        "${API_URL}${path}" \
        -d "${payload}" 2>&1
    )"; then
      printf '%s' "${output}"
      return 0
    fi
    attempt="$((attempt + 1))"
    if [[ "${attempt}" -ge "${RETRY_MAX_ATTEMPTS}" ]]; then
      echo "${output}" >&2
      return 1
    fi
    sleep "${RETRY_SLEEP_SECONDS}"
  done
}

api_post_empty_as() {
  local user_id="$1"
  local path="$2"
  local command_id
  local attempt=0
  local output
  command_id="$(new_command_id)"
  while true; do
    if output="$(
      curl -fsS \
        -H "X-User-Id: ${user_id}" \
        -H "X-Command-Id: ${command_id}" \
        -X POST \
        "${API_URL}${path}" 2>&1
    )"; then
      printf '%s' "${output}"
      return 0
    fi
    attempt="$((attempt + 1))"
    if [[ "${attempt}" -ge "${RETRY_MAX_ATTEMPTS}" ]]; then
      echo "${output}" >&2
      return 1
    fi
    sleep "${RETRY_SLEEP_SECONDS}"
  done
}

api_patch_as() {
  local user_id="$1"
  local path="$2"
  local payload="$3"
  local command_id
  local attempt=0
  local output
  command_id="$(new_command_id)"
  while true; do
    if output="$(
      curl -fsS \
        -H "Content-Type: application/json" \
        -H "X-User-Id: ${user_id}" \
        -H "X-Command-Id: ${command_id}" \
        -X PATCH \
        "${API_URL}${path}" \
        -d "${payload}" 2>&1
    )"; then
      printf '%s' "${output}"
      return 0
    fi
    attempt="$((attempt + 1))"
    if [[ "${attempt}" -ge "${RETRY_MAX_ATTEMPTS}" ]]; then
      echo "${output}" >&2
      return 1
    fi
    sleep "${RETRY_SLEEP_SECONDS}"
  done
}

api_get() {
  api_get_as "${ACTOR_USER_ID}" "$1"
}

api_post() {
  api_post_as "${ACTOR_USER_ID}" "$1" "$2"
}

create_rule() {
  local title="$1"
  local body="$2"
  api_post "/api/project-rules" "$(
    jq -n \
      --arg ws "${WS_ID}" \
      --arg pid "${PROJECT_ID}" \
      --arg title "${title}" \
      --arg body "${body}" \
      '{workspace_id:$ws,project_id:$pid,title:$title,body:$body}'
  )"
}

create_spec() {
  local title="$1"
  local status="$2"
  local tags_json="$3"
  local body="$4"
  api_post "/api/specifications" "$(
    jq -n \
      --arg ws "${WS_ID}" \
      --arg pid "${PROJECT_ID}" \
      --arg title "${title}" \
      --arg status "${status}" \
      --arg body "${body}" \
      --argjson tags "${tags_json}" \
      '{
        workspace_id:$ws,
        project_id:$pid,
        title:$title,
        status:$status,
        tags:$tags,
        body:$body
      }'
  )"
}

create_task() {
  local actor_id="$1"
  local spec_id="$2"
  local title="$3"
  local description="$4"
  local priority="$5"
  local assignee_id="$6"
  local labels_json="$7"
  local due_date="$8"
  local external_refs_json="${9:-[]}"

  api_post_as "${actor_id}" "/api/tasks" "$(
    jq -n \
      --arg ws "${WS_ID}" \
      --arg pid "${PROJECT_ID}" \
      --arg sid "${spec_id}" \
      --arg title "${title}" \
      --arg description "${description}" \
      --arg priority "${priority}" \
      --arg assignee "${assignee_id}" \
      --arg due "${due_date}" \
      --argjson labels "${labels_json}" \
      --argjson external_refs "${external_refs_json}" \
      '{
        workspace_id:$ws,
        project_id:$pid,
        specification_id:(if $sid == "" then null else $sid end),
        title:$title,
        description:$description,
        priority:$priority,
        assignee_id:(if $assignee == "" then null else $assignee end),
        labels:$labels,
        due_date:(if $due == "" then null else $due end),
        external_refs:$external_refs
      }'
  )"
}

create_bulk_spec_tasks() {
  local specification_id="$1"
  local titles_json="$2"
  local description="$3"
  local priority="$4"
  local assignee_id="$5"
  local labels_json="$6"
  api_post "/api/specifications/${specification_id}/tasks/bulk" "$(
    jq -n \
      --argjson titles "${titles_json}" \
      --arg description "${description}" \
      --arg priority "${priority}" \
      --arg assignee "${assignee_id}" \
      --argjson labels "${labels_json}" \
      '{
        titles:$titles,
        description:$description,
        priority:$priority,
        assignee_id:(if $assignee == "" then null else $assignee end),
        labels:$labels
      }'
  )"
}

create_note() {
  local actor_id="$1"
  local title="$2"
  local body="$3"
  local tags_json="$4"
  local task_id="$5"
  local specification_id="$6"
  local pinned="$7"
  api_post_as "${actor_id}" "/api/notes" "$(
    jq -n \
      --arg ws "${WS_ID}" \
      --arg pid "${PROJECT_ID}" \
      --arg title "${title}" \
      --arg body "${body}" \
      --argjson tags "${tags_json}" \
      --arg task_id "${task_id}" \
      --arg specification_id "${specification_id}" \
      --argjson pinned "${pinned}" \
      '{
        workspace_id:$ws,
        project_id:$pid,
        title:$title,
        body:$body,
        tags:$tags,
        task_id:(if $task_id == "" then null else $task_id end),
        specification_id:(if $specification_id == "" then null else $specification_id end),
        pinned:$pinned
      }'
  )"
}

add_comment() {
  local actor_id="$1"
  local task_id="$2"
  local body="$3"
  api_post_as "${actor_id}" "/api/tasks/${task_id}/comments" "$(
    jq -n --arg body "${body}" '{body:$body}'
  )" >/dev/null
}

watch_task() {
  local actor_id="$1"
  local task_id="$2"
  if ! api_post_empty_as "${actor_id}" "/api/tasks/${task_id}/watch" >/dev/null 2>&1; then
    echo "Warning: watch toggle failed for task ${task_id} and user ${actor_id}; continuing." >&2
  fi
}

wait_for_graph_projection() {
  local expected_tasks="$1"
  local expected_notes="$2"
  local expected_specs="$3"
  local expected_rules="$4"
  local timeout="$5"

  local started elapsed overview g_tasks g_notes g_specs g_rules
  started="$(date +%s)"

  while true; do
    if overview="$(api_get "/api/projects/${PROJECT_ID}/knowledge-graph/overview?top_limit=12" 2>/dev/null)"; then
      g_tasks="$(echo "${overview}" | jq -r '.counts.tasks // 0')"
      g_notes="$(echo "${overview}" | jq -r '.counts.notes // 0')"
      g_specs="$(echo "${overview}" | jq -r '.counts.specifications // 0')"
      g_rules="$(echo "${overview}" | jq -r '.counts.project_rules // 0')"
      if [[ "${g_tasks}" -ge "${expected_tasks}" && "${g_notes}" -ge "${expected_notes}" && "${g_specs}" -ge "${expected_specs}" && "${g_rules}" -ge "${expected_rules}" ]]; then
        GRAPH_OVERVIEW_JSON="${overview}"
        return 0
      fi
    fi

    elapsed="$(( $(date +%s) - started ))"
    if [[ "${elapsed}" -ge "${timeout}" ]]; then
      echo "Timed out waiting for graph projection consistency (${elapsed}s)." >&2
      if [[ -n "${overview:-}" ]]; then
        GRAPH_OVERVIEW_JSON="${overview}"
      fi
      return 1
    fi
    sleep 1
  done
}

echo "[1/14] Loading bootstrap..."
BOOTSTRAP="$(api_get "/api/bootstrap")"
WS_ID="${WORKSPACE_ID:-$(echo "${BOOTSTRAP}" | jq -r '.workspaces[0].id')}"
if [[ -z "${WS_ID}" || "${WS_ID}" == "null" ]]; then
  echo "Unable to resolve workspace id from /api/bootstrap." >&2
  exit 1
fi

LEAD_USER_ID="$(echo "${BOOTSTRAP}" | jq -r '.current_user.id')"
if [[ -z "${LEAD_USER_ID}" || "${LEAD_USER_ID}" == "null" ]]; then
  LEAD_USER_ID="${ACTOR_USER_ID}"
fi
if [[ -z "${BOT_USER_ID}" || "${BOT_USER_ID}" == "null" ]]; then
  BOT_USER_ID="$(echo "${BOOTSTRAP}" | jq -r '.users[] | select(.username == "codex-bot") | .id' | head -n 1 || true)"
fi
if [[ -z "${BOT_USER_ID}" || "${BOT_USER_ID}" == "null" ]]; then
  BOT_USER_ID="$(echo "${BOOTSTRAP}" | jq -r --arg lead "${LEAD_USER_ID}" '.users[] | select(.id != $lead) | .id' | head -n 1 || true)"
fi
if [[ -z "${BOT_USER_ID}" || "${BOT_USER_ID}" == "null" ]]; then
  BOT_USER_ID="${LEAD_USER_ID}"
fi

MEMBER_IDS_JSON="$(jq -nc --arg lead "${LEAD_USER_ID}" --arg bot "${BOT_USER_ID}" '[ $lead, $bot ] | unique')"

echo "[2/14] Creating complex demo project..."
PROJECT="$(api_post "/api/projects" "$(
  jq -n \
    --arg ws "${WS_ID}" \
    --arg name "${PROJECT_NAME}" \
    --arg desc "${PROJECT_DESCRIPTION}" \
    --argjson members "${MEMBER_IDS_JSON}" \
    '{
      workspace_id:$ws,
      name:$name,
      description:$desc,
      custom_statuses:["To do","In progress","Blocked","Ready for QA","Done"],
      member_user_ids:$members
    }'
)")"
PROJECT_ID="$(echo "${PROJECT}" | jq -r '.id')"
if [[ -z "${PROJECT_ID}" || "${PROJECT_ID}" == "null" ]]; then
  echo "Project creation failed; could not read project id." >&2
  exit 1
fi

echo "[3/14] Creating project rules..."
RULE_PAYMENT_GATE_ID="$(create_rule \
  "Rule 01: No shipment without captured payment and reservation lock" \
  "Before any shipment task transitions to Done, both payment capture and inventory reservation must be confirmed. Exception path requires incident note + owner approval." | jq -r '.id')"
RULE_IDEMPOTENCY_ID="$(create_rule \
  "Rule 02: Every write API must be idempotent" \
  "All command endpoints in checkout, reservation and fulfillment flows must support idempotency keys. Duplicate requests must not produce duplicate side-effects." | jq -r '.id')"
RULE_CORRELATION_ID="$(create_rule \
  "Rule 03: Correlation ID propagation is mandatory" \
  "Every event emitted from checkout through fulfillment must carry correlation_id and causation_id for timeline reconstruction and graph traceability." | jq -r '.id')"
RULE_PII_ID="$(create_rule \
  "Rule 04: PII-safe logs and notes" \
  "No card fragments, addresses or phone numbers in comments, notes or error traces. Use surrogate identifiers only." | jq -r '.id')"
RULE_INCIDENT_NOTE_ID="$(create_rule \
  "Rule 05: P1/P2 incidents require timeline note" \
  "For every P1/P2 incident, attach one timeline note to the incident orchestration task and tag with incident, timeline and service area." | jq -r '.id')"
RULE_RETRY_POLICY_ID="$(create_rule \
  "Rule 06: Retry policy with DLQ fallback" \
  "Async delivery retries must be bounded and forward to DLQ after threshold. Manual replay path must exist and be documented in runbook note." | jq -r '.id')"
RULE_RELEASE_GATES_ID="$(create_rule \
  "Rule 07: Release gate checklist required for prod deploy" \
  "No production release without explicit checklist note linked to release task and at least one reviewer comment." | jq -r '.id')"
RULE_OBSERVABILITY_ID="$(create_rule \
  "Rule 08: Graph context quality is a tracked metric" \
  "Track context-pack usefulness score and missing-link ratio weekly; investigate when trend degrades over two consecutive releases." | jq -r '.id')"

echo "[4/14] Creating specification graph backbone..."
SPEC_PAY="$(create_spec \
  "Spec 01: Checkout Resilience and Idempotent Payments" \
  "Ready" \
  '["payments","checkout","idempotency","risk"]' \
  "Goal: ensure retries never produce duplicate charges while preserving fast checkout UX. Includes idempotency keys, duplicate detection and capture event guarantees.")"
SPEC_PAY_ID="$(echo "${SPEC_PAY}" | jq -r '.id')"

SPEC_INV="$(create_spec \
  "Spec 02: Inventory Reservation Ledger and Expiry" \
  "Ready" \
  '["inventory","reservation","consistency","saga"]' \
  "Goal: preserve stock consistency under partial failures. Includes reservation ledger, expiry worker, release-on-failure and stock drift controls.")"
SPEC_INV_ID="$(echo "${SPEC_INV}" | jq -r '.id')"

SPEC_FUL="$(create_spec \
  "Spec 03: Fulfillment Orchestration and Courier Reliability" \
  "Ready" \
  '["fulfillment","orchestration","delivery","retry"]' \
  "Goal: orchestrate pick-pack-ship with strong dependency gates and reliable courier handoff. Includes retries, DLQ and timeline visibility.")"
SPEC_FUL_ID="$(echo "${SPEC_FUL}" | jq -r '.id')"

SPEC_NOTIF="$(create_spec \
  "Spec 04: Notifications, SLA Escalation and Customer Trust" \
  "Draft" \
  '["notifications","sla","incident","customer-trust"]' \
  "Goal: detect breaches early and communicate clearly to users and operators. Includes templates, escalation routing and SLA breach detector.")"
SPEC_NOTIF_ID="$(echo "${SPEC_NOTIF}" | jq -r '.id')"

SPEC_OPS="$(create_spec \
  "Spec 05: Incident Triage Copilot and Operational Intelligence" \
  "Draft" \
  '["ops","triage","graph-context","observability"]' \
  "Goal: shorten MTTR using graph-powered context retrieval, runbook recommendations and timeline assembly from correlated signals.")"
SPEC_OPS_ID="$(echo "${SPEC_OPS}" | jq -r '.id')"

echo "[5/14] Creating high-signal tasks..."
TASK_PAY_IDEMPOTENCY="$(create_task "${LEAD_USER_ID}" "${SPEC_PAY_ID}" \
  "Design payment intent idempotency contract" \
  "Define idempotency key scope, dedupe storage horizon and failure semantics for retry storms." \
  "High" "${LEAD_USER_ID}" '["payments","idempotency","api","risk"]' "" \
  '[{"url":"https://ipg.monri.com/en/documentation","title":"Monri API documentation","source":"external"}]' | jq -r '.id')"
TASK_PAY_OUTBOX="$(create_task "${BOT_USER_ID}" "${SPEC_PAY_ID}" \
  "Implement outbox for payment capture events" \
  "Guarantee capture event delivery with exactly-once projection semantics into fulfillment read model." \
  "High" "${BOT_USER_ID}" '["payments","eventing","reliability"]' "" '[]' | jq -r '.id')"
TASK_PAY_DUP_CHARGE="$(create_task "${BOT_USER_ID}" "${SPEC_PAY_ID}" \
  "Build duplicate charge detector and alerting" \
  "Create heuristics for duplicate attempts and raise high-priority incident signal when threshold is exceeded." \
  "Med" "${BOT_USER_ID}" '["payments","fraud","incident","alerts"]' "" '[]' | jq -r '.id')"

TASK_INV_LEDGER="$(create_task "${LEAD_USER_ID}" "${SPEC_INV_ID}" \
  "Implement reservation ledger aggregate" \
  "Persist reservation transitions and enforce non-negative inventory under concurrent checkout load." \
  "High" "${LEAD_USER_ID}" '["inventory","reservation","consistency"]' "" '[]' | jq -r '.id')"
TASK_INV_EXPIRY="$(create_task "${BOT_USER_ID}" "${SPEC_INV_ID}" \
  "Add reservation expiry worker with compensation flow" \
  "Expire stale reservations and publish release event consumed by checkout and fulfillment dependencies." \
  "High" "${BOT_USER_ID}" '["inventory","worker","saga","eventing"]' "" '[]' | jq -r '.id')"

TASK_FUL_SHIPMENT_GATE="$(create_task "${LEAD_USER_ID}" "${SPEC_FUL_ID}" \
  "Implement shipment gating by payment+inventory state" \
  "Shipment command must be blocked unless both capture and reservation conditions are satisfied." \
  "High" "${LEAD_USER_ID}" '["fulfillment","payments","inventory","dependency-gate"]' "" '[]' | jq -r '.id')"
TASK_FUL_RETRY_DLQ="$(create_task "${BOT_USER_ID}" "${SPEC_FUL_ID}" \
  "Implement courier handoff retry and DLQ policy" \
  "Bounded retries for courier publish; failed items go to DLQ with replay metadata and incident hook." \
  "Med" "${BOT_USER_ID}" '["fulfillment","retry","dlq","incident"]' "" '[]' | jq -r '.id')"

TASK_NOTIF_ESCALATION="$(create_task "${LEAD_USER_ID}" "${SPEC_NOTIF_ID}" \
  "Implement SLA escalation router" \
  "Route SLA breaches to on-call, service channel and project timeline notes with severity mapping." \
  "High" "${LEAD_USER_ID}" '["notifications","sla","incident","routing"]' "" '[]' | jq -r '.id')"
TASK_NOTIF_TEMPLATES="$(create_task "${BOT_USER_ID}" "${SPEC_NOTIF_ID}" \
  "Create delay and outage customer notification templates" \
  "Build localized templates with escalation-aware placeholders and safe fallback wording." \
  "Med" "${BOT_USER_ID}" '["notifications","templates","customer-trust"]' "" '[]' | jq -r '.id')"

TASK_OPS_CORR_ID="$(create_task "${LEAD_USER_ID}" "${SPEC_OPS_ID}" \
  "Implement correlation-id propagation middleware" \
  "Inject and propagate correlation_id + causation_id from API gateway to downstream event streams." \
  "High" "${LEAD_USER_ID}" '["ops","observability","correlation-id","eventing"]' "" '[]' | jq -r '.id')"
TASK_OPS_RUNBOOK_ENGINE="$(create_task "${BOT_USER_ID}" "${SPEC_OPS_ID}" \
  "Build runbook recommendation engine from graph context" \
  "Use related incident signatures, connected resources and rule hits to propose prioritized runbooks." \
  "High" "${BOT_USER_ID}" '["ops","triage","graph-context","runbook"]' "" '[]' | jq -r '.id')"
TASK_OPS_TIMELINE="$(create_task "${LEAD_USER_ID}" "${SPEC_OPS_ID}" \
  "Build incident timeline assembler service" \
  "Aggregate cross-service events into one timeline artifact used by incident commander and postmortem notes." \
  "Med" "${LEAD_USER_ID}" '["ops","timeline","incident","eventing"]' "" '[]' | jq -r '.id')"

TASK_ARCH_DECISIONS="$(create_task "${LEAD_USER_ID}" "" \
  "Prepare architecture decision records for dependency gates" \
  "Document tradeoffs for shipment gating, reservation expiry and escalation fanout." \
  "Med" "${LEAD_USER_ID}" '["architecture","governance","dependency-gate"]' "" '[]' | jq -r '.id')"
TASK_RELEASE_CHECKLIST="$(create_task "${BOT_USER_ID}" "" \
  "Create cross-team release checklist for commerce critical path" \
  "Define go/no-go checks involving payments, inventory, fulfillment and notifications." \
  "Med" "${BOT_USER_ID}" '["release","checklist","cross-team","risk"]' "" '[]' | jq -r '.id')"
TASK_GRAPH_METRICS="$(create_task "${BOT_USER_ID}" "" \
  "Instrument graph context quality metrics" \
  "Collect coverage and quality metrics for context pack and monitor trend per release." \
  "Med" "${BOT_USER_ID}" '["graph-context","metrics","observability"]' "" '[]' | jq -r '.id')"

echo "[6/14] Adding bulk backlog tasks..."
BULK_PAY_JSON="$(create_bulk_spec_tasks "${SPEC_PAY_ID}" \
  '["Add contract tests for retry matrix","Implement payment timeout circuit breaker","Create chargeback reconciliation export"]' \
  "Bulk tasks for payment hardening." "Med" "${BOT_USER_ID}" '["payments","hardening"]')"
BULK_INV_JSON="$(create_bulk_spec_tasks "${SPEC_INV_ID}" \
  '["Build stock drift reconciliation job","Expose reservation audit endpoint","Add replay tool for inventory events"]' \
  "Bulk tasks for inventory confidence." "Med" "${LEAD_USER_ID}" '["inventory","audit","replay"]')"
BULK_FUL_JSON="$(create_bulk_spec_tasks "${SPEC_FUL_ID}" \
  '["Implement warehouse adapter health probes","Add fulfillment lag dashboard","Create manual shipment unblock tool"]' \
  "Bulk tasks for fulfillment reliability." "Med" "${BOT_USER_ID}" '["fulfillment","reliability","support"]')"
BULK_NOTIF_JSON="$(create_bulk_spec_tasks "${SPEC_NOTIF_ID}" \
  '["Add on-call throttle for noisy incidents","Create customer comms quality checks"]' \
  "Bulk tasks for comms signal quality." "Low" "${LEAD_USER_ID}" '["notifications","quality"]')"
BULK_OPS_JSON="$(create_bulk_spec_tasks "${SPEC_OPS_ID}" \
  '["Index runbook snippets for retrieval","Add incident signature clustering job","Wire graph context into codex task prompts"]' \
  "Bulk tasks for operational intelligence." "Med" "${BOT_USER_ID}" '["ops","triage","graph-context"]')"

echo "[7/14] Creating notes across project/spec/task layers..."
NOTE_ARCH_MAP="$(create_note "${LEAD_USER_ID}" \
  "Architecture map: bounded contexts and event lanes" \
  "Payments -> Inventory -> Fulfillment -> Notifications. Keep correlation-id across all emitted events and include causation chain in incident notes." \
  '["architecture","eventing","graph-context"]' "" "" false | jq -r '.id')"
NOTE_PAY_FAIL="$(create_note "${LEAD_USER_ID}" \
  "Payment failure taxonomy" \
  "Failure classes: timeout, duplicate charge, gateway unavailable, fraud hold. Each class maps to mitigation task and escalation severity." \
  '["payments","risk","incident"]' "" "${SPEC_PAY_ID}" false | jq -r '.id')"
NOTE_INV_DRIFT="$(create_note "${BOT_USER_ID}" \
  "Inventory drift investigation template" \
  "Template fields: SKU, reservation path, release events observed, suspected source, rollback steps." \
  '["inventory","incident","template"]' "" "${SPEC_INV_ID}" false | jq -r '.id')"
NOTE_FUL_MATRIX="$(create_note "${LEAD_USER_ID}" \
  "Fulfillment dependency matrix" \
  "Shipment gate requires capture=true, reservation_state=locked, courier_channel=healthy." \
  '["fulfillment","dependency-gate","matrix"]' "" "${SPEC_FUL_ID}" false | jq -r '.id')"
NOTE_ESC_POLICY="$(create_note "${LEAD_USER_ID}" \
  "Escalation policy draft" \
  "SLA breach > 10m triggers incident channel, customer update draft and assigned owner task comment." \
  '["notifications","sla","incident"]' "" "${SPEC_NOTIF_ID}" false | jq -r '.id')"
NOTE_RUNBOOK="$(create_note "${BOT_USER_ID}" \
  "Ops runbook index" \
  "Runbooks are grouped by payment, inventory, fulfillment and comms classes. Use graph context to pick best-first runbook." \
  '["ops","runbook","graph-context"]' "" "${SPEC_OPS_ID}" true | jq -r '.id')"
NOTE_CHARGEBACK_TASK="$(create_note "${BOT_USER_ID}" \
  "Chargeback anomaly example" \
  "Observed duplicate-capture attempts after gateway retry spike. Link detector thresholds with incident response checklist." \
  '["payments","fraud","incident"]' "${TASK_PAY_DUP_CHARGE}" "${SPEC_PAY_ID}" false | jq -r '.id')"
NOTE_SHIP_EDGE="$(create_note "${LEAD_USER_ID}" \
  "Shipment gate edge cases" \
  "Edge cases include delayed capture acknowledgement and stale reservation release race." \
  '["fulfillment","edge-case","dependency-gate"]' "${TASK_FUL_SHIPMENT_GATE}" "${SPEC_FUL_ID}" false | jq -r '.id')"
NOTE_ESC_TIMELINE="$(create_note "${LEAD_USER_ID}" \
  "Escalation timeline from outage simulation" \
  "Timeline indicates routing delay due to missing priority mapping; fixed by explicit severity matrix." \
  '["incident","timeline","notifications"]' "${TASK_NOTIF_ESCALATION}" "${SPEC_NOTIF_ID}" false | jq -r '.id')"
NOTE_CORR_CHECK="$(create_note "${BOT_USER_ID}" \
  "Correlation-id logging checklist" \
  "Checklist for gateway, worker and consumer logs to guarantee trace continuity." \
  '["ops","observability","correlation-id"]' "${TASK_OPS_CORR_ID}" "${SPEC_OPS_ID}" false | jq -r '.id')"
NOTE_PROMPT_PATTERNS="$(create_note "${BOT_USER_ID}" \
  "Graph retrieval prompt patterns" \
  "Prompt should ask for dependencies, blocked risks, recent comments and related runbooks before proposing code changes." \
  '["graph-context","prompting","triage"]' "${TASK_OPS_RUNBOOK_ENGINE}" "${SPEC_OPS_ID}" false | jq -r '.id')"
NOTE_RELEASE_GO_NO_GO="$(create_note "${LEAD_USER_ID}" \
  "Release go/no-go checklist v1" \
  "Checklist covers capture integrity, reservation drift < 0.2%, shipment lag < 3m and escalation latency < 2m." \
  '["release","checklist","risk"]' "${TASK_RELEASE_CHECKLIST}" "" false | jq -r '.id')"
NOTE_METRICS_BASELINE="$(create_note "${BOT_USER_ID}" \
  "Metrics baseline before graph context rollout" \
  "Baseline MTTR=78m, repeated clarification questions=12 per incident, patch rollback rate=11%." \
  '["metrics","baseline","graph-context"]' "${TASK_GRAPH_METRICS}" "" false | jq -r '.id')"

echo "[8/14] Task comments, watchers and lifecycle events..."
add_comment "${LEAD_USER_ID}" "${TASK_PAY_IDEMPOTENCY}" "Idempotency window confirmed at 24h for now; evaluate 72h during load test."
add_comment "${BOT_USER_ID}" "${TASK_PAY_IDEMPOTENCY}" "Implemented key hash strategy draft; need review on collision policy."
add_comment "${BOT_USER_ID}" "${TASK_INV_EXPIRY}" "Worker emits compensation event with reason=reservation_timeout."
add_comment "${LEAD_USER_ID}" "${TASK_INV_EXPIRY}" "Add guard so compensation does not reopen already-shipped orders."
add_comment "${LEAD_USER_ID}" "${TASK_FUL_SHIPMENT_GATE}" "Gate should read payment + reservation snapshot atomically from projection model."
add_comment "${BOT_USER_ID}" "${TASK_FUL_SHIPMENT_GATE}" "Added fallback note: if projection stale >2m route to manual review lane."
add_comment "${BOT_USER_ID}" "${TASK_NOTIF_ESCALATION}" "Escalation fanout now includes incident channel and customer status page draft."
add_comment "${LEAD_USER_ID}" "${TASK_OPS_RUNBOOK_ENGINE}" "Prioritize runbooks by relationship path frequency and recent incident success."

watch_task "${LEAD_USER_ID}" "${TASK_PAY_OUTBOX}"
watch_task "${LEAD_USER_ID}" "${TASK_FUL_SHIPMENT_GATE}"
watch_task "${LEAD_USER_ID}" "${TASK_NOTIF_ESCALATION}"
watch_task "${BOT_USER_ID}" "${TASK_INV_EXPIRY}"
watch_task "${BOT_USER_ID}" "${TASK_FUL_RETRY_DLQ}"
watch_task "${BOT_USER_ID}" "${TASK_OPS_RUNBOOK_ENGINE}"

api_patch_as "${LEAD_USER_ID}" "/api/tasks/${TASK_PAY_IDEMPOTENCY}" "$(jq -n '{status:"In progress"}')" >/dev/null
api_post_empty_as "${BOT_USER_ID}" "/api/tasks/${TASK_PAY_OUTBOX}/complete" >/dev/null
api_patch_as "${BOT_USER_ID}" "/api/tasks/${TASK_INV_EXPIRY}" "$(jq -n '{status:"Blocked",priority:"High"}')" >/dev/null
api_patch_as "${LEAD_USER_ID}" "/api/tasks/${TASK_FUL_SHIPMENT_GATE}" "$(jq -n '{status:"In progress"}')" >/dev/null
api_patch_as "${LEAD_USER_ID}" "/api/tasks/${TASK_NOTIF_ESCALATION}" "$(jq -n '{status:"Ready for QA"}')" >/dev/null
api_post_empty_as "${BOT_USER_ID}" "/api/tasks/${TASK_NOTIF_TEMPLATES}/complete" >/dev/null
api_post_empty_as "${BOT_USER_ID}" "/api/tasks/${TASK_NOTIF_TEMPLATES}/reopen" >/dev/null
api_patch_as "${BOT_USER_ID}" "/api/tasks/${TASK_OPS_RUNBOOK_ENGINE}" "$(jq -n '{status:"In progress"}')" >/dev/null

api_patch_as "${LEAD_USER_ID}" "/api/specifications/${SPEC_PAY_ID}" "$(jq -n '{status:"In progress"}')" >/dev/null
api_patch_as "${LEAD_USER_ID}" "/api/specifications/${SPEC_INV_ID}" "$(jq -n '{status:"Ready"}')" >/dev/null
api_patch_as "${LEAD_USER_ID}" "/api/specifications/${SPEC_FUL_ID}" "$(jq -n '{status:"In progress"}')" >/dev/null
api_patch_as "${LEAD_USER_ID}" "/api/specifications/${SPEC_NOTIF_ID}" "$(jq -n '{status:"In progress"}')" >/dev/null
api_patch_as "${LEAD_USER_ID}" "/api/specifications/${SPEC_OPS_ID}" "$(jq -n '{status:"Ready"}')" >/dev/null

echo "[9/14] Cross-linking tasks and notes to enrich graph traversal paths..."
api_post_empty_as "${LEAD_USER_ID}" "/api/specifications/${SPEC_OPS_ID}/tasks/${TASK_ARCH_DECISIONS}/link" >/dev/null
api_post_empty_as "${LEAD_USER_ID}" "/api/specifications/${SPEC_OPS_ID}/tasks/${TASK_ARCH_DECISIONS}/unlink" >/dev/null
api_post_empty_as "${LEAD_USER_ID}" "/api/specifications/${SPEC_PAY_ID}/tasks/${TASK_ARCH_DECISIONS}/link" >/dev/null

api_post_empty_as "${BOT_USER_ID}" "/api/specifications/${SPEC_FUL_ID}/notes/${NOTE_RELEASE_GO_NO_GO}/link" >/dev/null
api_post_empty_as "${BOT_USER_ID}" "/api/specifications/${SPEC_FUL_ID}/notes/${NOTE_RELEASE_GO_NO_GO}/unlink" >/dev/null
api_post_empty_as "${BOT_USER_ID}" "/api/specifications/${SPEC_NOTIF_ID}/notes/${NOTE_RELEASE_GO_NO_GO}/link" >/dev/null

echo "[10/14] Gathering projection totals..."
TOTAL_TASKS="$(api_get "/api/tasks?workspace_id=${WS_ID}&project_id=${PROJECT_ID}&limit=200" | jq -r '.total')"
TOTAL_NOTES="$(api_get "/api/notes?workspace_id=${WS_ID}&project_id=${PROJECT_ID}&limit=200" | jq -r '.total')"
TOTAL_SPECS="$(api_get "/api/specifications?workspace_id=${WS_ID}&project_id=${PROJECT_ID}&limit=200" | jq -r '.total')"
TOTAL_RULES="$(api_get "/api/project-rules?workspace_id=${WS_ID}&project_id=${PROJECT_ID}&limit=200" | jq -r '.total')"

echo "[11/14] Waiting for Knowledge Graph projection..."
GRAPH_OVERVIEW_JSON=""
wait_for_graph_projection "${TOTAL_TASKS}" "${TOTAL_NOTES}" "${TOTAL_SPECS}" "${TOTAL_RULES}" "${WAIT_SECONDS}" || true
if [[ -z "${GRAPH_OVERVIEW_JSON}" ]]; then
  GRAPH_OVERVIEW_JSON="$(api_get "/api/projects/${PROJECT_ID}/knowledge-graph/overview?top_limit=12")"
fi

echo "[12/14] Fetching graph context artifacts..."
GRAPH_CONTEXT_JSON="$(api_get "/api/projects/${PROJECT_ID}/knowledge-graph/context-pack?limit=30")"
GRAPH_CONTEXT_FOCUS_SHIPMENT_JSON="$(api_get "/api/projects/${PROJECT_ID}/knowledge-graph/context-pack?focus_entity_type=Task&focus_entity_id=${TASK_FUL_SHIPMENT_GATE}&limit=30")"
GRAPH_CONTEXT_FOCUS_ESCALATION_JSON="$(api_get "/api/projects/${PROJECT_ID}/knowledge-graph/context-pack?focus_entity_type=Task&focus_entity_id=${TASK_NOTIF_ESCALATION}&limit=30")"
GRAPH_SUBGRAPH_JSON="$(api_get "/api/projects/${PROJECT_ID}/knowledge-graph/subgraph?limit_nodes=120&limit_edges=320")"

echo "[13/14] Writing demo artifacts..."
mkdir -p "${OUTPUT_ROOT}"
DEMO_DIR="${OUTPUT_ROOT}/${PROJECT_ID}"
mkdir -p "${DEMO_DIR}"

printf '%s\n' "${PROJECT}" > "${DEMO_DIR}/project.json"
printf '%s\n' "${GRAPH_OVERVIEW_JSON}" > "${DEMO_DIR}/overview.json"
printf '%s\n' "${GRAPH_CONTEXT_JSON}" > "${DEMO_DIR}/context-pack.json"
printf '%s\n' "${GRAPH_CONTEXT_FOCUS_SHIPMENT_JSON}" > "${DEMO_DIR}/context-pack-focus-shipment-gate.json"
printf '%s\n' "${GRAPH_CONTEXT_FOCUS_ESCALATION_JSON}" > "${DEMO_DIR}/context-pack-focus-escalation.json"
printf '%s\n' "${GRAPH_SUBGRAPH_JSON}" > "${DEMO_DIR}/subgraph.json"
printf '%s\n' "${BULK_PAY_JSON}" > "${DEMO_DIR}/bulk-payments.json"
printf '%s\n' "${BULK_INV_JSON}" > "${DEMO_DIR}/bulk-inventory.json"
printf '%s\n' "${BULK_FUL_JSON}" > "${DEMO_DIR}/bulk-fulfillment.json"
printf '%s\n' "${BULK_NOTIF_JSON}" > "${DEMO_DIR}/bulk-notifications.json"
printf '%s\n' "${BULK_OPS_JSON}" > "${DEMO_DIR}/bulk-ops.json"

jq -n \
  --arg api_url "${API_URL}" \
  --arg workspace_id "${WS_ID}" \
  --arg project_id "${PROJECT_ID}" \
  --arg project_name "${PROJECT_NAME}" \
  --arg lead_user_id "${LEAD_USER_ID}" \
  --arg bot_user_id "${BOT_USER_ID}" \
  --arg task_focus_1 "${TASK_FUL_SHIPMENT_GATE}" \
  --arg task_focus_2 "${TASK_NOTIF_ESCALATION}" \
  --arg task_arch "${TASK_ARCH_DECISIONS}" \
  --arg note_release "${NOTE_RELEASE_GO_NO_GO}" \
  --argjson totals "$(jq -n \
    --arg tasks "${TOTAL_TASKS}" \
    --arg notes "${TOTAL_NOTES}" \
    --arg specs "${TOTAL_SPECS}" \
    --arg rules "${TOTAL_RULES}" \
    '{tasks:($tasks|tonumber),notes:($notes|tonumber),specifications:($specs|tonumber),project_rules:($rules|tonumber)}')" \
  '{
    project: {
      id: $project_id,
      name: $project_name,
      workspace_id: $workspace_id
    },
    users: {
      lead_user_id: $lead_user_id,
      assistant_user_id: $bot_user_id
    },
    focus_entities: {
      shipment_gate_task_id: $task_focus_1,
      escalation_router_task_id: $task_focus_2,
      architecture_decision_task_id: $task_arch,
      release_checklist_note_id: $note_release
    },
    totals: $totals,
    endpoints: {
      overview: ($api_url + "/api/projects/" + $project_id + "/knowledge-graph/overview"),
      context_pack: ($api_url + "/api/projects/" + $project_id + "/knowledge-graph/context-pack?limit=30"),
      subgraph: ($api_url + "/api/projects/" + $project_id + "/knowledge-graph/subgraph?limit_nodes=120&limit_edges=320"),
      focus_shipment_gate: ($api_url + "/api/projects/" + $project_id + "/knowledge-graph/context-pack?focus_entity_type=Task&focus_entity_id=" + $task_focus_1 + "&limit=30"),
      focus_escalation_router: ($api_url + "/api/projects/" + $project_id + "/knowledge-graph/context-pack?focus_entity_type=Task&focus_entity_id=" + $task_focus_2 + "&limit=30")
    }
  }' > "${DEMO_DIR}/manifest.json"

cat > "${DEMO_DIR}/demo-questions.md" <<EOF
# Knowledge Graph Demo Questions

Project ID: \`${PROJECT_ID}\`
Workspace ID: \`${WS_ID}\`

## Comparison Setup

1. **Bez konteksta (kontrolni primjer)**  
   U Codex/agent prompt stavi samo pitanje bez Project selection ili bez Graph context bloka.
2. **Sa kontekstom (GraphRAG)**  
   U pitanju koristi isti prompt, ali na projektu \`${PROJECT_NAME}\` i, po potrebi, fokus na task:
   - Shipment Gate: \`${TASK_FUL_SHIPMENT_GATE}\`
   - Escalation Router: \`${TASK_NOTIF_ESCALATION}\`

## Prompts for Demo

1. "Koji su glavni rizici prije release-a i koje taskove prvo zatvoriti da minimizujemo incidente?"
2. "Ako shipment gate padne, koji su povezani artefakti, pravila i runbook note koje trebamo pogledati prije fix-a?"
3. "Napravi implementacijski plan za SLA escalation router uz dependency check prema payments i fulfillment."
4. "Koje informacije fale u trenutnom kontekstu da bih sigurno implementirao retry/DLQ za courier handoff?"
5. "Predlozi refactor koji smanjuje MTTR koristeci postojece task comments i notes."

## What To Highlight

- Sa graph kontekstom model prepoznaje veze Task <-> Specification <-> Note <-> Tag <-> User.
- Vidljivi su incident signali kroz \`COMMENTED_BY\`, \`WATCHED_BY\`, \`TAGGED_WITH\`, \`IMPLEMENTS\`.
- Focus context obično daje konkretnije i kraće planove jer su zavisnosti već eksplicitne.
- Bez konteksta odgovor je generičniji i često propušta project-specific constraints.
EOF

echo "[14/14] Done."
echo "DEMO_PROJECT_ID=${PROJECT_ID}"
echo "DEMO_PROJECT_NAME=${PROJECT_NAME}"
echo "WORKSPACE_ID=${WS_ID}"
echo "LEAD_USER_ID=${LEAD_USER_ID}"
echo "BOT_USER_ID=${BOT_USER_ID}"
echo "TOTAL_TASKS=${TOTAL_TASKS}"
echo "TOTAL_NOTES=${TOTAL_NOTES}"
echo "TOTAL_SPECS=${TOTAL_SPECS}"
echo "TOTAL_RULES=${TOTAL_RULES}"
echo "FOCUS_TASK_SHIPMENT_GATE=${TASK_FUL_SHIPMENT_GATE}"
echo "FOCUS_TASK_ESCALATION_ROUTER=${TASK_NOTIF_ESCALATION}"
echo "OUTPUT_DIR=${DEMO_DIR}"
echo
echo "Top relationships:"
echo "${GRAPH_OVERVIEW_JSON}" | jq -r '.top_relationships[] | "- " + .relationship + ": " + (.count|tostring)'
