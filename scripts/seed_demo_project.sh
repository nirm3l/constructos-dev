#!/usr/bin/env bash
set -euo pipefail

API_URL="${API_URL:-http://localhost:8080}"
USER_ID="${USER_ID:-00000000-0000-0000-0000-000000000001}"
WORKSPACE_ID="${WORKSPACE_ID:-}"
PROJECT_NAME="${PROJECT_NAME:-Demo: Smart Pantry Assistant}"
PROJECT_DESCRIPTION="${PROJECT_DESCRIPTION:-Demo projekat za walkthrough: specifications, tasks, notes, linking, bulk tokovi.}"

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Missing required command: $cmd" >&2
    exit 1
  fi
}

require_cmd curl
require_cmd jq

new_command_id() {
  printf "seed-%s-%s-%s" "$(date +%s)" "$RANDOM" "$RANDOM"
}

api_get() {
  local path="$1"
  curl -fsS \
    -H "X-User-Id: ${USER_ID}" \
    "${API_URL}${path}"
}

api_post() {
  local path="$1"
  local payload="$2"
  curl -fsS \
    -H "Content-Type: application/json" \
    -H "X-User-Id: ${USER_ID}" \
    -H "X-Command-Id: $(new_command_id)" \
    -X POST \
    "${API_URL}${path}" \
    -d "${payload}"
}

api_post_empty() {
  local path="$1"
  curl -fsS \
    -H "X-User-Id: ${USER_ID}" \
    -H "X-Command-Id: $(new_command_id)" \
    -X POST \
    "${API_URL}${path}"
}

api_patch() {
  local path="$1"
  local payload="$2"
  curl -fsS \
    -H "Content-Type: application/json" \
    -H "X-User-Id: ${USER_ID}" \
    -H "X-Command-Id: $(new_command_id)" \
    -X PATCH \
    "${API_URL}${path}" \
    -d "${payload}"
}

echo "[1/8] Loading bootstrap..."
BOOTSTRAP="$(api_get "/api/bootstrap")"
WS_ID="${WORKSPACE_ID:-$(echo "${BOOTSTRAP}" | jq -r '.workspaces[0].id')}"
if [[ -z "${WS_ID}" || "${WS_ID}" == "null" ]]; then
  echo "Unable to resolve workspace id from bootstrap." >&2
  exit 1
fi

echo "[2/8] Creating demo project..."
PROJECT_PAYLOAD="$(
  jq -n \
    --arg ws "${WS_ID}" \
    --arg name "${PROJECT_NAME}" \
    --arg desc "${PROJECT_DESCRIPTION}" \
    '{workspace_id:$ws,name:$name,description:$desc}'
)"
PROJECT="$(api_post "/api/projects" "${PROJECT_PAYLOAD}")"
PROJECT_ID="$(echo "${PROJECT}" | jq -r '.id')"

echo "[3/8] Creating demo specifications..."
SPEC1_PAYLOAD="$(
  jq -n \
    --arg ws "${WS_ID}" \
    --arg pid "${PROJECT_ID}" \
    --arg title "Spec 01: Auth & Onboarding" \
    --arg body "## Goal
Omoguciti korisniku da za manje od 2 minuta napravi nalog i doda prvu namirnicu.

## Scope
- Email/password signup i login
- Jednostavan onboarding (3 koraka)
- Persistencija sesije

## Acceptance Criteria
1. Korisnik moze kreirati nalog i verifikovati email.
2. Nakon logina vidi onboarding checklistu.
3. Posle refresh-a sesija ostaje aktivna." \
    '{workspace_id:$ws,project_id:$pid,title:$title,body:$body,status:"Ready"}'
)"
SPEC1="$(api_post "/api/specifications" "${SPEC1_PAYLOAD}")"
SPEC1_ID="$(echo "${SPEC1}" | jq -r '.id')"

SPEC2_PAYLOAD="$(
  jq -n \
    --arg ws "${WS_ID}" \
    --arg pid "${PROJECT_ID}" \
    --arg title "Spec 02: Inventory & Expiry Alerts" \
    --arg body "## Goal
Pomoci korisniku da prati stanje zaliha i rok trajanja namirnica.

## Scope
- CRUD za pantry items
- Datum isteka i low-stock prag
- Obavestenja za uskoro istekle artikle

## Acceptance Criteria
1. Korisnik moze dodati artikl i kolicinu.
2. Sistem oznacava artikle koji isticnu u naredna 3 dana.
3. Dashboard prikazuje low-stock sekciju." \
    '{workspace_id:$ws,project_id:$pid,title:$title,body:$body,status:"Ready"}'
)"
SPEC2="$(api_post "/api/specifications" "${SPEC2_PAYLOAD}")"
SPEC2_ID="$(echo "${SPEC2}" | jq -r '.id')"

echo "[4/8] Seeding spec-linked tasks and notes (single + bulk)..."
T1="$(api_post "/api/specifications/${SPEC1_ID}/tasks" "$(jq -n '{title:"Implement signup/login forms",priority:"High",labels:["auth","frontend"]}')")"
T1_ID="$(echo "${T1}" | jq -r '.id')"

BULK1="$(api_post "/api/specifications/${SPEC1_ID}/tasks/bulk" "$(jq -n '{titles:["Create onboarding checklist component","Persist session token securely","Add e2e flow for first login"]}')")"

N1="$(api_post "/api/specifications/${SPEC1_ID}/notes" "$(jq -n --arg body "# Auth decisions

- Koristiti short-lived access + refresh strategiju.
- Login greske mapirati na user-friendly poruke.
- Onboarding state cuvati server-side." '{title:"Auth decisions",body:$body,tags:["auth","adr"]}')")"
N1_ID="$(echo "${N1}" | jq -r '.id')"

T2="$(api_post "/api/specifications/${SPEC2_ID}/tasks" "$(jq -n '{title:"Create pantry item domain model",priority:"High",labels:["inventory","backend"]}')")"
T2_ID="$(echo "${T2}" | jq -r '.id')"

BULK2="$(api_post "/api/specifications/${SPEC2_ID}/tasks/bulk" "$(jq -n '{titles:["Build expiry alert job","Create low-stock dashboard widget","Add API filters for expiring items"]}')")"

N2="$(api_post "/api/specifications/${SPEC2_ID}/notes" "$(jq -n --arg body "# Inventory UX notes

1. Brzo dodavanje artikla preko FAB dugmeta.
2. Vizuelno oznaciti artikle pred istek (zuto/crveno).
3. Dodati sugestije kategorija (dairy, produce, frozen)." '{title:"Inventory UX notes",body:$body,tags:["inventory","ux"]}')")"
N2_ID="$(echo "${N2}" | jq -r '.id')"

echo "[5/8] Creating standalone task/note and demonstrating link/unlink..."
GENERAL_TASK="$(
  api_post "/api/tasks" "$(
    jq -n \
      --arg ws "${WS_ID}" \
      --arg pid "${PROJECT_ID}" \
      '{workspace_id:$ws,project_id:$pid,title:"Set up CI pipeline for demo project",priority:"Med",labels:["devops"]}'
  )"
)"
GENERAL_TASK_ID="$(echo "${GENERAL_TASK}" | jq -r '.id')"

GENERAL_NOTE="$(
  api_post "/api/notes" "$(
    jq -n \
      --arg ws "${WS_ID}" \
      --arg pid "${PROJECT_ID}" \
      '{workspace_id:$ws,project_id:$pid,title:"Kickoff note",body:"Dogovor: prvo zavrsiti onboarding pa inventory modul.",tags:["kickoff"]}'
  )"
)"
GENERAL_NOTE_ID="$(echo "${GENERAL_NOTE}" | jq -r '.id')"

api_post_empty "/api/specifications/${SPEC1_ID}/tasks/${GENERAL_TASK_ID}/link" >/dev/null
api_post_empty "/api/specifications/${SPEC1_ID}/tasks/${GENERAL_TASK_ID}/unlink" >/dev/null
api_post_empty "/api/specifications/${SPEC2_ID}/tasks/${GENERAL_TASK_ID}/link" >/dev/null

api_post_empty "/api/specifications/${SPEC1_ID}/notes/${GENERAL_NOTE_ID}/link" >/dev/null
api_post_empty "/api/specifications/${SPEC1_ID}/notes/${GENERAL_NOTE_ID}/unlink" >/dev/null
api_post_empty "/api/specifications/${SPEC2_ID}/notes/${GENERAL_NOTE_ID}/link" >/dev/null

echo "[6/8] Demonstrating lifecycle actions..."
api_patch "/api/tasks/${T1_ID}" "$(jq -n '{status:"In progress"}')" >/dev/null
api_post_empty "/api/tasks/${T2_ID}/complete" >/dev/null
api_post_empty "/api/tasks/${T2_ID}/reopen" >/dev/null
api_post_empty "/api/notes/${N1_ID}/pin" >/dev/null
api_post_empty "/api/notes/${N1_ID}/unpin" >/dev/null
api_patch "/api/specifications/${SPEC2_ID}" "$(jq -n '{status:"In progress"}')" >/dev/null

echo "[7/8] Collecting outputs..."
S1_TASKS="$(api_get "/api/tasks?workspace_id=${WS_ID}&project_id=${PROJECT_ID}&specification_id=${SPEC1_ID}&limit=200")"
S2_TASKS="$(api_get "/api/tasks?workspace_id=${WS_ID}&project_id=${PROJECT_ID}&specification_id=${SPEC2_ID}&limit=200")"
S1_NOTES="$(api_get "/api/notes?workspace_id=${WS_ID}&project_id=${PROJECT_ID}&specification_id=${SPEC1_ID}&limit=200")"
S2_NOTES="$(api_get "/api/notes?workspace_id=${WS_ID}&project_id=${PROJECT_ID}&specification_id=${SPEC2_ID}&limit=200")"
PROJECT_SPECS="$(api_get "/api/specifications?workspace_id=${WS_ID}&project_id=${PROJECT_ID}&limit=200")"

TOTAL_TASKS="$(api_get "/api/tasks?workspace_id=${WS_ID}&project_id=${PROJECT_ID}&limit=200" | jq -r '.total')"
TOTAL_NOTES="$(api_get "/api/notes?workspace_id=${WS_ID}&project_id=${PROJECT_ID}&limit=200" | jq -r '.total')"
TOTAL_SPECS="$(echo "${PROJECT_SPECS}" | jq -r '.total')"

echo "[8/8] Demo seeded successfully."
echo "DEMO_PROJECT_ID=${PROJECT_ID}"
echo "SPEC_AUTH_ID=${SPEC1_ID}"
echo "SPEC_INVENTORY_ID=${SPEC2_ID}"
echo "TOTAL_SPECS=${TOTAL_SPECS}"
echo "TOTAL_TASKS=${TOTAL_TASKS}"
echo "TOTAL_NOTES=${TOTAL_NOTES}"
echo "SPEC1_TASK_COUNT=$(echo "${S1_TASKS}" | jq -r '.total')"
echo "SPEC2_TASK_COUNT=$(echo "${S2_TASKS}" | jq -r '.total')"
echo "SPEC1_NOTE_COUNT=$(echo "${S1_NOTES}" | jq -r '.total')"
echo "SPEC2_NOTE_COUNT=$(echo "${S2_NOTES}" | jq -r '.total')"

echo "--- SPECIFICATIONS ---"
echo "${PROJECT_SPECS}" | jq -r '.items[] | "- " + .title + " :: " + .status + " (" + .id + ")"'

echo "--- SPEC 1 TASKS ---"
echo "${S1_TASKS}" | jq -r '.items[] | "- [" + .status + "] " + .title + " (" + .id + ")"'

echo "--- SPEC 2 TASKS ---"
echo "${S2_TASKS}" | jq -r '.items[] | "- [" + .status + "] " + .title + " (" + .id + ")"'

echo "--- SPEC 1 NOTES ---"
echo "${S1_NOTES}" | jq -r '.items[] | "- " + .title + " (" + .id + ")"'

echo "--- SPEC 2 NOTES ---"
echo "${S2_NOTES}" | jq -r '.items[] | "- " + .title + " (" + .id + ")"'

echo "--- BULK RESULTS (SPEC 1) ---"
echo "${BULK1}" | jq '{created,failed,total,results}'

echo "--- BULK RESULTS (SPEC 2) ---"
echo "${BULK2}" | jq '{created,failed,total,results}'
