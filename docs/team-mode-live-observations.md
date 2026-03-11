# Team Mode Live Observations

## 2026-03-10: Tetris Prompt Run After Fresh Reset

Project:
- `27d98f64-0663-57d0-b931-789e4028d6d9`

Observed runtime behavior:
- Lead-first kickoff did dispatch Developer work successfully.
- Developer task `96348ce8-6923-5e25-90fc-957ab5753f1a` received `TaskAutomationRequested` with source `lead_kickoff_dispatch` and entered `running`.
- Lead task `c3f08e53-a395-5ae8-920f-4ae233ed96e4` correctly remained in `triage` with blocking gate `lead_waiting_merge_ready_developer`.
- QA task stayed idle, which is correct before explicit Lead handoff.

Observed product gaps:
- Setup/orchestration still needed manual repair during project creation:
  - Event Storming stayed enabled and was patched off afterward.
  - Canonical Team Mode `task_relationships` were only partially auto-populated and were patched afterward.
- Kickoff reporting was stale or incorrect:
  - Lead comment/event payload said Developer was still `idle`.
  - Persisted state already showed Developer `running`.
  - Improvement needed: kickoff summaries must re-read persisted automation state before final user-facing reporting.
- Delivery verification overstated deploy progress during the deferred Lead phase:
  - Observability-only predeploy URLs on the Lead task were being treated as deploy execution evidence.
  - Improvement needed: only structured deploy snapshots, explicit deploy refs, deploy notes, or postdeploy probe markers should satisfy deploy execution evidence.

Current improvement status:
- Prompt guidance now requires persisted-state re-read after kickoff before summarizing progress.
- Delivery verification now ignores bare task-level HTTP refs when evaluating deploy execution evidence.

## 2026-03-10: Tetris Deploy Health Blocker

Observed runtime behavior:
- Developer completed successfully and handed off merge-ready evidence to Lead.
- Lead synthesized deployment assets, merged to `main`, and started `docker compose -p constructos-ws-default up -d`.
- The managed runtime container `constructos-ws-default-web` started and bound host port `6768`, but Lead remained blocked on runtime health.
- Probes to `http://gateway:6768/health` returned `000` or `404`, and later live inspection showed connection resets from `task-app`.

Confirmed deployment artifact state:
- The real project repository under `data/workspace/.constructos/repos/tetris` contains the expected generated files:
  - `docker-compose.yml`
  - `nginx/conf.d/default.conf`
  - `health`
- The generated nginx config does define `location = /health { return 200 'ok'; }`.

Confirmed runtime mismatch:
- The running container mount sources are:
  - `/home/app/workspace/.constructos/repos/tetris`
  - `/home/app/workspace/.constructos/repos/tetris/nginx/conf.d`
- Inside the runtime container:
  - `/etc/nginx/conf.d` is empty
  - `/usr/share/nginx/html` contains only unexpected directories, not the generated app files
- On the host, the real repository path is under:
  - `/home/m4tr1x/task-management/data/workspace/.constructos/repos/tetris`

Likely root cause:
- `docker compose` is being executed from inside `task-app` against the host Docker socket using container-visible paths.
- The Docker daemon resolves bind mounts against the host filesystem, not the container filesystem.
- Because of that, deployment uses `/home/app/workspace/...` on the host instead of the real workspace path, so the runtime container mounts the wrong content.

Improvements needed:
- Introduce canonical host-path resolution for project repositories before executing Docker Compose through the host Docker socket.
- Ensure compose bind mounts are written using host-visible paths, or run deploy commands from a host path context that matches the daemon view.
- Add a deployment regression that verifies generated runtime files are visible inside the launched container, not only in the app container worktree.
