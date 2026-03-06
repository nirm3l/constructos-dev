# MCP Tool: setup_project_orchestration

This document defines practical usage for the `setup_project_orchestration` MCP tool.

## Purpose

Run a complete staged setup in one call:
- create or resolve project
- enable/disable `team_mode`, `git_delivery`, `docker_compose`
- apply plugin configs with strict validation
- optionally seed default Team Mode tasks
- run workflow verification

Primary usage is chat-led project setup where the assistant gathers only missing inputs, then executes this tool.

## Input Contract

Required:
- `name` or `project_id`

Common optional fields:
- `short_description: string`
- `workspace_id: string`
- `enable_team_mode: bool`
- `enable_git_delivery: bool`
- `enable_docker_compose: bool`
- `docker_port: int`
- `team_mode_config: object|string`
- `git_delivery_config: object|string`
- `docker_compose_config: object|string`
- `expected_event_storming_enabled: bool`
- `seed_team_tasks: bool` (default `true`)
- `command_id: string`

Dependency rule:
- `docker_compose=true` requires `git_delivery=true`.
- If `team_mode=true` and `git_delivery=false`, Git Delivery is auto-enabled.

## Output Contract (stable)

Top-level fields:
- `contract_version: 1`
- `ok: bool`
- `blocking: bool`
- `execution_state: "setup_complete"|"setup_failed"`
- `project: { id, workspace_id, name, created, link }`
- `requested: { ... }`
- `effective: { team_mode_enabled, git_delivery_enabled, docker_compose_enabled }`
- `plugins: { team_mode, git_delivery, docker_compose }`
- `seeded_entities: { team_mode_tasks? }`
- `verification: { team_mode?, delivery? }`
- `steps: [ { id, title, status, blocking, attempts, error?, reason? } ]`
- `adjustments: string[]`
- `errors: object[]`

## Example: Chat-guided create + Team Mode + Docker

Request:
```json
{
  "name": "Tetris",
  "short_description": "Web game",
  "workspace_id": "<ws_id>",
  "enable_team_mode": true,
  "enable_docker_compose": true,
  "docker_port": 6768,
  "seed_team_tasks": true,
  "command_id": "chat-setup-001"
}
```

Typical response shape:
```json
{
  "contract_version": 1,
  "ok": true,
  "blocking": false,
  "execution_state": "setup_complete",
  "project": {
    "id": "<project_id>",
    "workspace_id": "<ws_id>",
    "name": "Tetris",
    "created": true,
    "link": "?tab=projects&project=<project_id>"
  },
  "requested": {
    "team_mode_enabled": true,
    "git_delivery_enabled": true,
    "docker_compose_enabled": true,
    "docker_port": 6768,
    "seed_team_tasks": true
  },
  "effective": {
    "team_mode_enabled": true,
    "git_delivery_enabled": true,
    "docker_compose_enabled": true
  },
  "steps": [
    {"id": "create_project", "status": "ok", "attempts": 1},
    {"id": "set_plugin_team_mode", "status": "ok", "attempts": 1},
    {"id": "set_plugin_git_delivery", "status": "ok", "attempts": 1},
    {"id": "set_plugin_docker_compose", "status": "ok", "attempts": 1},
    {"id": "seed_team_mode_tasks", "status": "ok", "attempts": 1}
  ]
}
```

## Example: Existing project plugin update only

Request:
```json
{
  "project_id": "<project_id>",
  "workspace_id": "<ws_id>",
  "enable_team_mode": false,
  "enable_git_delivery": true,
  "enable_docker_compose": false,
  "seed_team_tasks": false
}
```

## Example: Blocking dependency error

Request:
```json
{
  "project_id": "<project_id>",
  "workspace_id": "<ws_id>",
  "enable_team_mode": false,
  "enable_git_delivery": false,
  "enable_docker_compose": true
}
```

Response excerpt:
```json
{
  "ok": false,
  "blocking": true,
  "execution_state": "setup_failed",
  "steps": [
    {
      "id": "validate_plugin_dependencies",
      "status": "error",
      "blocking": true,
      "error": {
        "type": "validation_error",
        "status_code": 422,
        "message": "docker_compose requires git_delivery enabled"
      }
    }
  ]
}
```

For missing-input interactive flow, the tool returns `422` with:
- `next_question`
- `next_input_key`
- `missing_inputs`
- `resolved_inputs`
- `setup_path`

## Chat UX Notes

- The assistant should ask one missing input at a time.
- If user already provided multiple required inputs, skip redundant questions.
- Once required inputs are complete, call `setup_project_orchestration`.
- After success, return project link: `?tab=projects&project=<project_id>`.
