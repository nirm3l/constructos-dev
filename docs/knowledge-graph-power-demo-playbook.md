# Knowledge Graph Power Demo Playbook

## Purpose

This playbook demonstrates why GraphRAG context outperforms "flat" context when answering implementation questions and planning code changes in a complex project.

The demo uses:
- cross-domain specifications (payments, inventory, fulfillment, notifications, ops)
- linked tasks/notes/rules with overlapping tags
- task comments and watchers (human + agent)
- status changes and relinking events that update the graph projection

## Seed Script

Run:

```bash
./scripts/seed_graph_power_demo.sh
```

Optional environment variables:

```bash
API_URL=http://localhost:8080
ACTOR_USER_ID=00000000-0000-0000-0000-000000000001
WORKSPACE_ID=<workspace-id>
BOT_USER_ID=<assistant-user-id>
PROJECT_NAME="GraphRAG Demo: ..."
OUTPUT_ROOT=data/graph-power-demo
WAIT_SECONDS=120
./scripts/seed_graph_power_demo.sh
```

After completion, inspect:
- `data/graph-power-demo/<project_id>/manifest.json`
- `data/graph-power-demo/<project_id>/overview.json`
- `data/graph-power-demo/<project_id>/context-pack.json`
- `data/graph-power-demo/<project_id>/context-pack-focus-shipment-gate.json`
- `data/graph-power-demo/<project_id>/context-pack-focus-escalation.json`
- `data/graph-power-demo/<project_id>/subgraph.json`
- `data/graph-power-demo/<project_id>/demo-questions.md`

## Demo Flow (Recommended)

1. Open the created project in UI and show:
   - Project Rules
   - Specifications
   - Tasks + Notes
   - Knowledge Graph panel
2. In Knowledge Graph panel, open fullscreen and highlight:
   - multiple entity types
   - dense connections around risk/incident tasks
   - selected node details (degree + connected edges)
3. Show `context-pack.json` and `context-pack-focus-*.json`.
4. Ask the same implementation question twice:
   - once without project context
   - once with project selected and graph context enabled
5. Compare output quality:
   - dependency awareness
   - references to exact tasks/notes/rules
   - fewer clarification loops
   - safer sequencing of code changes

## Suggested Prompt Pairs

Use the exact same prompt text for both runs.

1. "Koji su glavni release rizici i kojim redoslijedom zatvaramo taskove?"
2. "Ako shipment gate pukne, šta sve moramo provjeriti prije rollback odluke?"
3. "Napravi plan implementacije SLA escalation routera, uz dependency check sa payments i fulfillment."
4. "Koje informacije još nedostaju za siguran retry/DLQ rollout?"
5. "Predloži refactor koji smanjuje MTTR i reci koje artefakte koristiš kao dokaz."

## What "Good" Looks Like

A strong graph-aware answer should:
- cite project-specific dependencies (not generic best practices only)
- mention linked specifications, rules, notes and comments
- identify blockers and sequencing constraints
- produce concrete next coding steps with scope boundaries
- surface uncertainty explicitly where graph coverage is weak

## Quick API Verification

Use `manifest.json` values:

```bash
curl -sS "http://localhost:8080/api/projects/<project_id>/knowledge-graph/overview" | jq
curl -sS "http://localhost:8080/api/projects/<project_id>/knowledge-graph/context-pack?limit=30" | jq
curl -sS "http://localhost:8080/api/projects/<project_id>/knowledge-graph/subgraph?limit_nodes=120&limit_edges=320" | jq
```

Focused context (example):

```bash
curl -sS "http://localhost:8080/api/projects/<project_id>/knowledge-graph/context-pack?focus_entity_type=Task&focus_entity_id=<task_id>&limit=30" | jq
```

