#!/usr/bin/env bash
set -euo pipefail

API_URL="${API_URL:-http://localhost:8080}"
USER_ID="${USER_ID:-00000000-0000-0000-0000-000000000001}"
WORKSPACE_ID="${WORKSPACE_ID:-}"
PROJECT_NAME="${PROJECT_NAME:-Demo: Browser Tetris Delivery Project ($(date -u +%Y-%m-%dT%H:%MZ))}"
PROJECT_DESCRIPTION="${PROJECT_DESCRIPTION:-Execution-ready demo project for building a full Tetris game in the browser with clear specs, detailed tasks, and implementation notes for Codex-driven delivery.}"
OUTPUT_ROOT="${OUTPUT_ROOT:-data/tetris-demo}"
WAIT_SECONDS="${WAIT_SECONDS:-90}"
RETRY_MAX_ATTEMPTS="${RETRY_MAX_ATTEMPTS:-6}"
RETRY_SLEEP_SECONDS="${RETRY_SLEEP_SECONDS:-0.25}"
PURGE_EXISTING_PROJECTS="${PURGE_EXISTING_PROJECTS:-true}"

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
  printf "tetris-demo-%s-%s-%s" "$(date +%s%N)" "$BASHPID" "$RANDOM"
}

api_get() {
  local path="$1"
  local attempt=0
  local output
  while true; do
    if output="$(curl -fsS -H "X-User-Id: ${USER_ID}" "${API_URL}${path}" 2>&1)"; then
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

api_post() {
  local path="$1"
  local payload="$2"
  local command_id
  local attempt=0
  local output
  command_id="$(new_command_id)"
  while true; do
    if output="$(
      curl -fsS \
        -H "Content-Type: application/json" \
        -H "X-User-Id: ${USER_ID}" \
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

api_post_empty() {
  local path="$1"
  local command_id
  local attempt=0
  local output
  command_id="$(new_command_id)"
  while true; do
    if output="$(
      curl -fsS \
        -H "X-User-Id: ${USER_ID}" \
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

api_patch() {
  local path="$1"
  local payload="$2"
  local command_id
  local attempt=0
  local output
  command_id="$(new_command_id)"
  while true; do
    if output="$(
      curl -fsS \
        -H "Content-Type: application/json" \
        -H "X-User-Id: ${USER_ID}" \
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

api_delete() {
  local path="$1"
  local command_id
  local attempt=0
  local output
  command_id="$(new_command_id)"
  while true; do
    if output="$(
      curl -fsS \
        -H "X-User-Id: ${USER_ID}" \
        -H "X-Command-Id: ${command_id}" \
        -X DELETE \
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
  )" >/dev/null
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
  local title="$1"
  local description="$2"
  local priority="$3"
  local status="$4"
  local specification_id="$5"
  local assignee_id="$6"
  local labels_json="$7"
  api_post "/api/tasks" "$(
    jq -n \
      --arg ws "${WS_ID}" \
      --arg pid "${PROJECT_ID}" \
      --arg title "${title}" \
      --arg description "${description}" \
      --arg priority "${priority}" \
      --arg status "${status}" \
      --arg sid "${specification_id}" \
      --arg assignee "${assignee_id}" \
      --argjson labels "${labels_json}" \
      '{
        workspace_id:$ws,
        project_id:$pid,
        title:$title,
        description:$description,
        priority:$priority,
        status:$status,
        specification_id:(if $sid == "" then null else $sid end),
        assignee_id:(if $assignee == "" then null else $assignee end),
        labels:$labels
      }'
  )"
}

create_note() {
  local title="$1"
  local body="$2"
  local tags_json="$3"
  local task_id="$4"
  local specification_id="$5"
  local pinned="$6"
  api_post "/api/notes" "$(
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
  local task_id="$1"
  local body="$2"
  api_post "/api/tasks/${task_id}/comments" "$(jq -n --arg body "${body}" '{body:$body}')" >/dev/null
}

safe_json_or_empty() {
  local raw="$1"
  if [[ -z "${raw}" ]]; then
    echo "{}"
    return
  fi
  if echo "${raw}" | jq -e . >/dev/null 2>&1; then
    echo "${raw}"
    return
  fi
  echo "{}"
}

wait_for_graph_projection() {
  local expected_tasks="$1"
  local expected_notes="$2"
  local expected_specs="$3"
  local started elapsed overview tasks notes specs
  started="$(date +%s)"

  while true; do
    if overview="$(api_get "/api/projects/${PROJECT_ID}/knowledge-graph/overview?top_limit=12" 2>/dev/null)"; then
      tasks="$(echo "${overview}" | jq -r '.counts.tasks // 0')"
      notes="$(echo "${overview}" | jq -r '.counts.notes // 0')"
      specs="$(echo "${overview}" | jq -r '.counts.specifications // 0')"
      if [[ "${tasks}" -ge "${expected_tasks}" && "${notes}" -ge "${expected_notes}" && "${specs}" -ge "${expected_specs}" ]]; then
        GRAPH_OVERVIEW_JSON="${overview}"
        return 0
      fi
    fi
    elapsed="$(( $(date +%s) - started ))"
    if [[ "${elapsed}" -ge "${WAIT_SECONDS}" ]]; then
      GRAPH_OVERVIEW_JSON="${overview:-{}}"
      return 1
    fi
    sleep 1
  done
}

echo "[1/12] Loading bootstrap..."
BOOTSTRAP="$(api_get "/api/bootstrap")"
WS_ID="${WORKSPACE_ID:-$(echo "${BOOTSTRAP}" | jq -r '.workspaces[0].id')}"
if [[ -z "${WS_ID}" || "${WS_ID}" == "null" ]]; then
  echo "Unable to resolve workspace id from /api/bootstrap" >&2
  exit 1
fi

ASSIGNEE_ID="$(echo "${BOOTSTRAP}" | jq -r '.current_user.id')"
if [[ -z "${ASSIGNEE_ID}" || "${ASSIGNEE_ID}" == "null" ]]; then
  ASSIGNEE_ID="${USER_ID}"
fi

if [[ "${PURGE_EXISTING_PROJECTS}" == "true" ]]; then
  echo "[2/12] Purging existing workspace projects..."
  EXISTING_PROJECT_IDS="$(
    echo "${BOOTSTRAP}" | jq -r --arg ws "${WS_ID}" '.projects[] | select(.workspace_id == $ws) | .id'
  )"
  if [[ -n "${EXISTING_PROJECT_IDS}" ]]; then
    while IFS= read -r pid; do
      if [[ -z "${pid}" ]]; then
        continue
      fi
      api_delete "/api/projects/${pid}" >/dev/null
    done <<<"${EXISTING_PROJECT_IDS}"
  fi
fi

echo "[3/12] Creating Tetris demo project..."
PROJECT="$(api_post "/api/projects" "$(
  jq -n \
    --arg ws "${WS_ID}" \
    --arg name "${PROJECT_NAME}" \
    --arg desc "${PROJECT_DESCRIPTION}" \
    --arg assignee "${ASSIGNEE_ID}" \
    '{
      workspace_id:$ws,
      name:$name,
      description:$desc,
      custom_statuses:["To do","In progress","Blocked","Ready for QA","Done"],
      member_user_ids:[$assignee]
    }'
)")"
PROJECT_ID="$(echo "${PROJECT}" | jq -r '.id')"

echo "[4/12] Creating project rules..."
create_rule \
  "Keep game logic deterministic and pure" \
  "Movement, collision, rotation, line clear and scoring logic must be implemented as pure functions so they are directly unit-testable."
create_rule \
  "One task, one outcome" \
  "Every task implementation must include explicit validation of acceptance criteria in the task description before moving to Ready for QA."
create_rule \
  "No UI-driven logic coupling" \
  "Renderer may read game state, but must not mutate gameplay state directly. Gameplay ticks and input reducers own all state changes."
create_rule \
  "Document algorithmic decisions" \
  "When implementing rotation/wall kicks, lock delay, gravity curve, or scoring, record short ADR notes linked to the relevant specification."

echo "[5/12] Creating specifications..."
SPEC1_BODY="$(cat <<'EOF'
## Goal
Implement a reliable Tetris gameplay core that can run deterministically in the browser.

## Scope
- Board representation (10x20 visible + spawn buffer)
- Tetromino data model and spawn system
- Movement, collision, rotation, hard drop, soft drop, lock behavior
- Line clear detection and game-over detection

## Acceptance Criteria
1. All seven tetrominoes spawn correctly with expected orientation.
2. Piece movement and rotation always respect collision boundaries.
3. Single/multi-line clears update board state correctly.
4. Game ends when a new piece cannot legally spawn.
EOF
)"
SPEC1="$(create_spec "Spec 01: Core Gameplay Engine" "Ready" '["engine","core-logic","deterministic"]' "${SPEC1_BODY}")"
SPEC1_ID="$(echo "${SPEC1}" | jq -r '.id')"

SPEC2_BODY="$(cat <<'EOF'
## Goal
Provide responsive rendering and controls for desktop and mobile web.

## Scope
- Canvas-based board renderer
- Main loop integration (logic tick + render frame)
- Keyboard controls and optional on-screen controls
- HUD: score, level, lines, next queue, hold piece
- Pause/resume/restart states

## Acceptance Criteria
1. Board renders at stable frame rate without input lag.
2. Keyboard controls (left/right/rotate/drop/pause) are mapped and debounced correctly.
3. HUD values are always synchronized with gameplay state.
4. Game can pause/resume/restart without stale state artifacts.
EOF
)"
SPEC2="$(create_spec "Spec 02: Rendering and Player Controls" "Ready" '["ui","canvas","input","hud"]' "${SPEC2_BODY}")"
SPEC2_ID="$(echo "${SPEC2}" | jq -r '.id')"

SPEC3_BODY="$(cat <<'EOF'
## Goal
Ship a polished gameplay experience with progression, persistence and quality validation.

## Scope
- Scoring model and level speed progression
- Local high-score and session persistence
- Audio and mute preferences
- QA coverage and release checklist

## Acceptance Criteria
1. Scoring and level progression follow a documented formula.
2. High score and user settings persist between reloads.
3. Core gameplay logic has unit tests for key edge cases.
4. A release checklist note exists and is linked to validation tasks.
EOF
)"
SPEC3="$(create_spec "Spec 03: Progression, Persistence and QA" "In progress" '["scoring","persistence","qa"]' "${SPEC3_BODY}")"
SPEC3_ID="$(echo "${SPEC3}" | jq -r '.id')"

echo "[6/12] Creating detailed tasks..."
TASK1_DESC="$(cat <<'EOF'
## Goal
Implement board, piece and spawn primitives as the foundation for all gameplay behavior.

## Implementation Notes
- Create immutable board utilities (`createBoard`, `cloneBoard`, `isCellOccupied`).
- Model tetromino definitions as rotation-state arrays with origin metadata.
- Implement spawn logic with deterministic randomizer hook (default 7-bag).
- Ensure spawn position supports standard Tetris board width.

## Acceptance Criteria
1. Unit tests verify board dimensions and empty board initialization.
2. Unit tests verify all 7 tetromino definitions are valid and spawnable.
3. Spawn returns failure state when blocked (used for game-over flow).
EOF
)"
TASK1="$(create_task "Engine: board model and tetromino spawn" "${TASK1_DESC}" "High" "In progress" "${SPEC1_ID}" "${ASSIGNEE_ID}" '["engine","core","spawn","tests"]')"
TASK1_ID="$(echo "${TASK1}" | jq -r '.id')"

TASK2_DESC="$(cat <<'EOF'
## Goal
Add movement and collision resolution that is deterministic and side-effect free.

## Implementation Notes
- Implement move reducer for left/right/down with collision rejection.
- Add hard drop position resolver and soft drop stepping behavior.
- Keep collision checks centralized (`canPlacePiece`).
- Return next immutable state from reducers.

## Acceptance Criteria
1. Piece cannot move through walls or occupied cells.
2. Hard drop lands on highest valid lock row.
3. Soft drop can be held without skipping collision validation.
EOF
)"
TASK2="$(create_task "Engine: movement and collision reducer" "${TASK2_DESC}" "High" "To do" "${SPEC1_ID}" "${ASSIGNEE_ID}" '["engine","collision","movement"]')"
TASK2_ID="$(echo "${TASK2}" | jq -r '.id')"

TASK3_DESC="$(cat <<'EOF'
## Goal
Implement rotation using SRS-like kick tables for practical browser gameplay.

## Implementation Notes
- Add clockwise and counterclockwise rotation actions.
- Implement kick attempts with ordered offsets.
- Store per-piece rotation index and validate each kick candidate.
- Keep kick table isolated for future tuning.

## Acceptance Criteria
1. Rotation near walls attempts kicks before failing.
2. Rotation fails cleanly when no kick candidate is valid.
3. I-piece behavior is covered with dedicated edge-case tests.
EOF
)"
TASK3="$(create_task "Engine: rotation + wall kick system" "${TASK3_DESC}" "High" "To do" "${SPEC1_ID}" "${ASSIGNEE_ID}" '["engine","rotation","wall-kick","tests"]')"
TASK3_ID="$(echo "${TASK3}" | jq -r '.id')"

TASK4_DESC="$(cat <<'EOF'
## Goal
Finalize lock, line-clear and game-over transitions.

## Implementation Notes
- Lock active piece into board after drop/timeout condition.
- Detect and clear 1-4 filled lines in one lock cycle.
- Compact board and count cleared lines per action.
- Emit game-over when next spawn fails.

## Acceptance Criteria
1. Clearing multiple lines in a single lock is supported.
2. Board compaction leaves no orphan holes in cleared rows.
3. Game-over state triggers exactly once per failed spawn.
EOF
)"
TASK4="$(create_task "Engine: lock cycle, line clear, game over" "${TASK4_DESC}" "High" "Ready for QA" "${SPEC1_ID}" "${ASSIGNEE_ID}" '["engine","line-clear","game-over","qa"]')"
TASK4_ID="$(echo "${TASK4}" | jq -r '.id')"

TASK5_DESC="$(cat <<'EOF'
## Goal
Implement canvas renderer that reflects engine state with minimal frame jitter.

## Implementation Notes
- Render static board, active piece, ghost piece and grid.
- Separate render concerns from gameplay reducer.
- Keep draw functions composable by layer.
- Add basic responsive scaling for narrow viewports.

## Acceptance Criteria
1. Active piece and settled blocks never desynchronize from state.
2. Ghost piece updates instantly after movement/rotation.
3. Frame pacing remains stable under repeated input.
EOF
)"
TASK5="$(create_task "UI: canvas renderer and visual layers" "${TASK5_DESC}" "Med" "In progress" "${SPEC2_ID}" "${ASSIGNEE_ID}" '["ui","canvas","rendering","responsive"]')"
TASK5_ID="$(echo "${TASK5}" | jq -r '.id')"

TASK6_DESC="$(cat <<'EOF'
## Goal
Create robust input mapping for keyboard and optional touch controls.

## Implementation Notes
- Map keys: arrows, Z/X, Space, Shift/C, P/Escape.
- Implement repeat timing for left/right/down.
- Prevent page scroll on active game controls.
- Add touch buttons for mobile fallback.

## Acceptance Criteria
1. Control latency feels immediate and repeat timing is predictable.
2. Browser scroll/focus conflicts are avoided during active play.
3. Control bindings are discoverable in help modal/note.
EOF
)"
TASK6="$(create_task "UI: keyboard + touch input handling" "${TASK6_DESC}" "High" "Blocked" "${SPEC2_ID}" "${ASSIGNEE_ID}" '["input","keyboard","mobile","ux"]')"
TASK6_ID="$(echo "${TASK6}" | jq -r '.id')"

TASK7_DESC="$(cat <<'EOF'
## Goal
Build HUD panel with all player-critical telemetry.

## Implementation Notes
- Show score, level, total cleared lines.
- Show next queue (at least 3) and hold piece preview.
- Add game state badge (Running, Paused, Game Over).
- Keep HUD updates derived from single source of truth.

## Acceptance Criteria
1. HUD values update every relevant gameplay transition.
2. Hold/next previews match engine queue state.
3. HUD layout remains readable on 13" laptop and mobile portrait.
EOF
)"
TASK7="$(create_task "UI: HUD (score, level, lines, next, hold)" "${TASK7_DESC}" "Med" "To do" "${SPEC2_ID}" "${ASSIGNEE_ID}" '["hud","ui","telemetry"]')"
TASK7_ID="$(echo "${TASK7}" | jq -r '.id')"

TASK8_DESC="$(cat <<'EOF'
## Goal
Add scoring and level progression mechanics with transparent formula.

## Implementation Notes
- Define base scores for single/double/triple/tetris clears.
- Increase gravity every N lines.
- Apply optional soft-drop/hard-drop bonus points.
- Document formula in code comments and release note.

## Acceptance Criteria
1. Score increments are deterministic for identical action sequences.
2. Level progression influences tick speed as designed.
3. Formula is documented in markdown note linked to this task.
EOF
)"
TASK8="$(create_task "Gameplay: scoring + level progression" "${TASK8_DESC}" "High" "To do" "${SPEC3_ID}" "${ASSIGNEE_ID}" '["scoring","progression","balancing"]')"
TASK8_ID="$(echo "${TASK8}" | jq -r '.id')"

TASK9_DESC="$(cat <<'EOF'
## Goal
Persist essential player data across sessions without backend dependency.

## Implementation Notes
- Persist high score, mute preference and last control layout to localStorage.
- Add safe parse/validation for stale or corrupted payloads.
- Version storage payload for migration readiness.

## Acceptance Criteria
1. Reload keeps high score and preferences.
2. Corrupted localStorage payload does not crash app.
3. Storage schema versioning is implemented and documented.
EOF
)"
TASK9="$(create_task "Platform: local persistence for score/settings" "${TASK9_DESC}" "Med" "To do" "${SPEC3_ID}" "${ASSIGNEE_ID}" '["persistence","storage","resilience"]')"
TASK9_ID="$(echo "${TASK9}" | jq -r '.id')"

TASK10_DESC="$(cat <<'EOF'
## Goal
Create focused automated test coverage for the riskiest gameplay scenarios.

## Implementation Notes
- Add unit tests for collision, rotation kicks and line clears.
- Add smoke e2e test: start game -> clear one line -> game over.
- Keep tests deterministic via seeded piece queue helper.

## Acceptance Criteria
1. Test suite covers edge cases that previously caused regressions.
2. Failing tests clearly indicate logic vs rendering failures.
3. CI-ready command for tests is documented in project note.
EOF
)"
TASK10="$(create_task "QA: automated tests for critical gameplay paths" "${TASK10_DESC}" "High" "Ready for QA" "${SPEC3_ID}" "${ASSIGNEE_ID}" '["qa","tests","ci"]')"
TASK10_ID="$(echo "${TASK10}" | jq -r '.id')"

echo "[7/12] Creating detailed notes..."
NOTE1_BODY="$(cat <<'EOF'
# Architecture Note: Game State Shape

Recommended top-level state:
- `board`: settled cells
- `activePiece`: shape, position, rotation
- `queue`: upcoming pieces (7-bag)
- `hold`: held piece + hasSwappedThisTurn
- `stats`: score, level, lines
- `timing`: gravity interval, lock delay
- `ui`: paused, gameOver, muted

Why:
- Clear separation of deterministic gameplay and view state.
- Easy to snapshot and replay state transitions for debugging.
EOF
)"
NOTE1="$(create_note "ADR: Tetris state model" "${NOTE1_BODY}" '["adr","architecture","engine"]' "" "${SPEC1_ID}" "true")"
NOTE1_ID="$(echo "${NOTE1}" | jq -r '.id')"

NOTE2_BODY="$(cat <<'EOF'
# Input Mapping Contract

Keyboard defaults:
- Left/Right: horizontal movement
- Down: soft drop
- Up or X: rotate CW
- Z: rotate CCW
- Space: hard drop
- Shift/C: hold
- P or Escape: pause toggle

Design constraints:
1. Key repeat for movement should feel smooth but not skip collision checks.
2. No accidental browser scrolling during active game.
3. Input abstraction should support touch controls without branching gameplay logic.
EOF
)"
NOTE2="$(create_note "Input UX contract" "${NOTE2_BODY}" '["input","ux","controls"]' "${TASK6_ID}" "${SPEC2_ID}" "false")"
NOTE2_ID="$(echo "${NOTE2}" | jq -r '.id')"

NOTE3_BODY="$(cat <<'EOF'
# Scoring and Progression Proposal

Base scoring:
- Single: 100 * level
- Double: 300 * level
- Triple: 500 * level
- Tetris: 800 * level

Drop bonuses:
- Soft drop: +1 per cell
- Hard drop: +2 per cell

Level progression:
- Increase level every 10 cleared lines.
- Gravity interval decreases per level with lower bound to preserve playability.
EOF
)"
NOTE3="$(create_note "Scoring formula draft" "${NOTE3_BODY}" '["scoring","balancing","formula"]' "${TASK8_ID}" "${SPEC3_ID}" "false")"
NOTE3_ID="$(echo "${NOTE3}" | jq -r '.id')"

NOTE4_BODY="$(cat <<'EOF'
# Release Checklist (MVP)

1. Run unit tests for engine logic and verify all pass.
2. Play manual session on desktop keyboard for 10+ minutes.
3. Validate mobile controls on at least one touch device.
4. Verify high score persists across hard refresh.
5. Verify pause/resume/restart paths do not leak stale state.
EOF
)"
NOTE4="$(create_note "MVP release checklist" "${NOTE4_BODY}" '["release","qa","checklist"]' "${TASK10_ID}" "${SPEC3_ID}" "false")"
NOTE4_ID="$(echo "${NOTE4}" | jq -r '.id')"

NOTE5_BODY="$(cat <<'EOF'
# Codex Execution Brief

Implementation order recommendation:
1. Complete Spec 01 tasks first (engine correctness baseline).
2. Then Spec 02 (renderer + controls) once reducers are stable.
3. Finish with Spec 03 (scoring, persistence, QA hardening).

Execution policy:
- Always update task status and comments when acceptance criteria are reached.
- If blocked, write explicit blocker reason and mitigation proposal.
EOF
)"
NOTE5="$(create_note "Codex implementation brief" "${NOTE5_BODY}" '["codex","delivery","workflow"]' "" "" "true")"
NOTE5_ID="$(echo "${NOTE5}" | jq -r '.id')"

echo "[8/12] Adding task comments for context trail..."
add_comment "${TASK1_ID}" "Start from pure board/piece primitives first; renderer should consume state only."
add_comment "${TASK3_ID}" "Wall kick behavior should be table-driven to allow tuning without reducer rewrites."
add_comment "${TASK6_ID}" "Blocked until we settle repeat-rate constants and mobile fallback button layout."
add_comment "${TASK8_ID}" "Use scoring note as single source of truth and keep formulas covered by tests."
add_comment "${TASK10_ID}" "Tests should be deterministic via controlled queue seeds; avoid flaky timing assertions."

echo "[9/12] Applying a few state transitions..."
api_patch "/api/tasks/${TASK2_ID}" "$(jq -n '{status:"In progress"}')" >/dev/null
api_patch "/api/tasks/${TASK4_ID}" "$(jq -n '{status:"Ready for QA"}')" >/dev/null
api_patch "/api/tasks/${TASK6_ID}" "$(jq -n '{status:"Blocked"}')" >/dev/null
api_patch "/api/tasks/${TASK10_ID}" "$(jq -n '{status:"Ready for QA"}')" >/dev/null

echo "[10/12] Waiting for graph projection..."
if ! wait_for_graph_projection "10" "5" "3"; then
  echo "Warning: graph projection did not reach expected counts within ${WAIT_SECONDS}s." >&2
fi

echo "[11/12] Collecting outputs..."
PROJECT_SPECS="$(api_get "/api/specifications?workspace_id=${WS_ID}&project_id=${PROJECT_ID}&limit=200")"
PROJECT_TASKS="$(api_get "/api/tasks?workspace_id=${WS_ID}&project_id=${PROJECT_ID}&limit=200")"
PROJECT_NOTES="$(api_get "/api/notes?workspace_id=${WS_ID}&project_id=${PROJECT_ID}&limit=200")"
GRAPH_CONTEXT_RAW="$(api_get "/api/projects/${PROJECT_ID}/knowledge-graph/context-pack?limit=40" || true)"
GRAPH_SUBGRAPH_RAW="$(api_get "/api/projects/${PROJECT_ID}/knowledge-graph/subgraph?limit_nodes=90&limit_edges=260" || true)"
PROJECT_SPECS_JSON="$(safe_json_or_empty "${PROJECT_SPECS}")"
PROJECT_TASKS_JSON="$(safe_json_or_empty "${PROJECT_TASKS}")"
PROJECT_NOTES_JSON="$(safe_json_or_empty "${PROJECT_NOTES}")"
GRAPH_OVERVIEW="$(safe_json_or_empty "${GRAPH_OVERVIEW_JSON:-}")"
GRAPH_CONTEXT="$(safe_json_or_empty "${GRAPH_CONTEXT_RAW}")"
GRAPH_SUBGRAPH="$(safe_json_or_empty "${GRAPH_SUBGRAPH_RAW}")"

mkdir -p "${OUTPUT_ROOT}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUTPUT_JSON="${OUTPUT_ROOT}/tetris-demo-${STAMP}.json"
LATEST_JSON="${OUTPUT_ROOT}/latest.json"

jq -n \
  --arg generated_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg api_url "${API_URL}" \
  --arg workspace_id "${WS_ID}" \
  --arg project_id "${PROJECT_ID}" \
  --arg project_name "${PROJECT_NAME}" \
  --arg specs_json "${PROJECT_SPECS_JSON}" \
  --arg tasks_json "${PROJECT_TASKS_JSON}" \
  --arg notes_json "${PROJECT_NOTES_JSON}" \
  --arg graph_overview_json "${GRAPH_OVERVIEW}" \
  --arg graph_context_json "${GRAPH_CONTEXT:-{}}" \
  --arg graph_subgraph_json "${GRAPH_SUBGRAPH:-{}}" \
  '{
    generated_at:$generated_at,
    api_url:$api_url,
    workspace_id:$workspace_id,
    project:{
      id:$project_id,
      name:$project_name
    },
    specs:($specs_json | fromjson? // {}),
    tasks:($tasks_json | fromjson? // {}),
    notes:($notes_json | fromjson? // {}),
    graph_overview:($graph_overview_json | fromjson? // {}),
    graph_context_pack:($graph_context_json | fromjson? // {}),
    graph_subgraph:($graph_subgraph_json | fromjson? // {})
  }' >"${OUTPUT_JSON}"
cp "${OUTPUT_JSON}" "${LATEST_JSON}"

echo "[12/12] Done."
echo "PROJECT_ID=${PROJECT_ID}"
echo "WORKSPACE_ID=${WS_ID}"
echo "SPEC_1_ID=${SPEC1_ID}"
echo "SPEC_2_ID=${SPEC2_ID}"
echo "SPEC_3_ID=${SPEC3_ID}"
echo "TOTAL_SPECS=$(echo "${PROJECT_SPECS}" | jq -r '.total')"
echo "TOTAL_TASKS=$(echo "${PROJECT_TASKS}" | jq -r '.total')"
echo "TOTAL_NOTES=$(echo "${PROJECT_NOTES}" | jq -r '.total')"
echo "OUTPUT_JSON=${OUTPUT_JSON}"
echo "LATEST_JSON=${LATEST_JSON}"
echo "--- SPECIFICATIONS ---"
echo "${PROJECT_SPECS}" | jq -r '.items[] | "- " + .title + " [" + .status + "] (" + .id + ")"'
echo "--- TASKS ---"
echo "${PROJECT_TASKS}" | jq -r '.items[] | "- [" + .status + "] " + .title + " (" + .id + ")"'
echo "--- NOTES ---"
echo "${PROJECT_NOTES}" | jq -r '.items[] | "- " + .title + " (" + .id + ")"'
