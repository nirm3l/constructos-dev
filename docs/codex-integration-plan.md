# Plan Integracije Codex Support-a (MCP + FastMCP)

## 1. Scope automatizacije (MVP)

- `Task -> Codex run` aktivirati samo za taskove koji su oznaceni za automation (`label: codex` ili `automation=true`).
- Definisati ishode run-a:
  - `completed` (task zavrsen)
  - `commented` (komentar sa rezultatima/blokerima)
  - `failed` (komentar sa greskom, task ostaje otvoren)
- Codex moze kreirati taskove samo u dozvoljenim workspace/project granicama.

## 2. Domain/Event model (u postojecem CQRS + ES)

- U `app/features/tasks/domain.py` dodati evente:
  - `TaskAutomationRequested`
  - `TaskAutomationStarted`
  - `TaskAutomationCompleted`
  - `TaskAutomationFailed`
- U `app/shared/eventing_rebuild.py` prosiriti projekciju task stanja:
  - `automation_state` (`idle/queued/running/completed/failed`)
  - `last_agent_run_at`
  - `last_agent_error`
- Uvesti `system user` identitet za Codex akcije radi cistog audita.

## 3. FastMCP server kao alatni sloj

- Dodati modul npr. `app/features/agents/mcp_server.py`.
- Izloziti minimalni set MCP tool-ova:
  - `list_tasks(workspace_id, project_id, filters)`
  - `get_task(task_id)`
  - `create_task(workspace_id, project_id, title, description, labels, due_date)`
  - `update_task(task_id, patch)`
  - `complete_task(task_id)`
  - `add_task_comment(task_id, body)`
- Svaki tool mora raditi auth + scope validaciju (`workspace/project`), analogno `ensure_role`.

## 4. Codex Runner worker (orchestration)

- Uvesti worker koji slusa:
  - `TaskAutomationRequested` event
  - i/ili endpoint `Run with Codex`
- Runner:
  - Ucitava task context (task, project, recent activity, komentare)
  - Pokrece Codex sesiju
  - Koristi MCP tool-ove za operacije nad taskovima
- Zavrsetak run-a:
  - ako je posao gotov -> `complete_task`
  - ako nije -> `add_task_comment` sa outputom i blockerima
- Za sve mutacije koristiti idempotency (`X-Command-Id`) da ne duplira side effects.

## 5. API i UI integracija

- Dodati endpoint-e:
  - `POST /api/tasks/{task_id}/automation/run`
  - `GET /api/tasks/{task_id}/automation`
- U task detail UI dodati:
  - dugme `Run with Codex`
  - indikator stanja (`queued/running/completed/failed`)
  - prikaz zadnjeg agent komentara

## 6. Security i operativni guardrails

- MCP auth token + periodična rotacija.
- Hard scope: agent vidi samo odobrene workspaces/projects.
- Tool allowlist (bez opasnih/destruktivnih operacija).
- Timeout, retry i max broj tool poziva po run-u.
- Audit trail:
  - task_id
  - actor (`system/codex`)
  - korisceni alati
  - finalni ishod

## 7. Test plan

- Unit testovi:
  - automation eventi
  - projekcija novih task polja
- Integration testovi:
  - `run` endpoint -> `complete` ili `comment`
- Security testovi:
  - cross-workspace pristup vraca `403`
- Idempotency testovi:
  - isti run request ne smije duplirati side effects

## 8. Preporuceni redoslijed implementacije

1. Eventi + read model (`automation_state`)
2. FastMCP tool layer
3. Runner worker
4. API/UI trigger + status prikaz
5. Security hardening + testovi

