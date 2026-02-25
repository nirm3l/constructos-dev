# Agent Instructions

## Language Policy
- Use English only for all code changes.
- Use English only for:
  - identifiers
  - comments and docstrings
  - user-facing UI text and API error messages
  - tests and documentation updates
- Do not introduce Bosnian/Croatian/Serbian text in code or docs.
- If touched text is non-English, translate it to English as part of the change.

## Deployment Safety (Control Plane)
- Treat `license-control-plane` and `license-control-plane-backup` as protected services.
- Use fixed Compose project names:
  - app stack: `constructos-app`
  - control-plane stack: `constructos-cp`
- Never stop, remove, or recreate control-plane containers unless the user explicitly requests it in that turn.
- `docker compose ... down --remove-orphans` is allowed for app-only operations when explicitly scoped to project `constructos-app`.
- Never run `docker compose -f docker-compose.license-control-plane.yml down` unless explicitly requested.
- For app-stack resets/redeploys, operate only on app compose files and scope commands with `-p constructos-app`.
- Never run unscoped compose cleanup commands that could target both stacks.
- If a command would impact protected control-plane services, stop and ask for explicit confirmation first.
