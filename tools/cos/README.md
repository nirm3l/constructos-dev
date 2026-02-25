# COS CLI

`cos` is a thin wrapper around Codex with automatic application MCP injection.
By default, `cos` runs on the host and executes Codex inside the app Docker container (`task-app`).

Core behavior:
- injects your application MCP server by default (`task-management-tools`)
- prepends hidden wrapper instructions every run
- keeps Codex in control of implementation work (file edits, commands, tests)
- supports layered config (`~/.cos/config.toml` and `./.cos/config.toml`)
- uses Docker backend by default (`codex_backend = "docker"`)
- auto-enables `--skip-git-repo-check` for `cos exec` when backend is Docker

## Requirements

- Python 3.10+
- Docker CLI available in `PATH`
- Running app container with Codex installed (default: `task-app`)
- Optional for git push from Docker backend: set `GITHUB_PAT` in `task-app` container environment.

For local backend (`codex_backend = "local"`):
- Codex CLI available in `PATH` (`codex --help`)

## Install (Recommended, Ubuntu + macOS)

Use isolated user-level install with `pipx`.

### Ubuntu
```bash
sudo apt-get update
sudo apt-get install -y pipx
pipx ensurepath
```

### macOS
```bash
brew install pipx
pipx ensurepath
```

### Install `cos`
From repository root:
```bash
pipx install --force ./tools/cos
```

From GitHub (no local clone required):
```bash
pipx install --force "git+https://github.com/nirm3l/constructos.git@main#subdirectory=tools/cos"
```

Verify:
```bash
cos --help
cos chat --help
cos --version
```

Upgrade:
```bash
pipx upgrade constructos-cos
```

## Alternative Install Script

From repository root:
```bash
./tools/cos/scripts/install.sh
```

Script modes:
- `--method pipx` (default, recommended)
- `--method link` (symlink install, no isolated environment)
- `--system --method link` (installs `/usr/local/bin/cos`)

## Uninstall

```bash
./tools/cos/scripts/uninstall.sh
```

Or direct:
```bash
pipx uninstall constructos-cos
```

## Build Artifacts (wheel + sdist)

From repository root:
```bash
./tools/cos/scripts/build.sh
```

This creates:
- `tools/cos/dist/*.whl`
- `tools/cos/dist/*.tar.gz`

Install from built wheel:
```bash
pipx install --force tools/cos/dist/*.whl
```

Install from GitHub release wheel:
```bash
pipx install --force "https://github.com/nirm3l/constructos/releases/download/cos-vX.Y.Z/constructos_cos-X.Y.Z-py3-none-any.whl"
```

## Usage

```bash
# interactive session
cos chat

# resume the last interactive session
cos resume --last

# resume a specific session id
cos resume 019c94dd-beb0-70a2-9401-41095aa9be6f

# resume an application chat Codex thread id (docker backend auto-detects session home)
cos resume 019c94dd-092a-7163-ad81-8553c41564cb

# interactive with initial request
cos chat "Implement CI cache improvements and run tests"

# non-interactive execution
cos exec "Implement retry logic in notification worker"

# diagnostics
cos doctor
cos doctor --app-mcp-url https://example.com --json
```

For Docker backend, `cos doctor` also reports git push readiness checks:
- `git_in_docker`
- `github_pat_in_docker`
- `git_push_auth_in_docker`

Useful options:
- `--repo /path/to/repo`
- `--app-mcp-url http://localhost:8091/mcp`
- `--codex-backend docker` or `--codex-backend local`
- `--docker-container task-app`
- `--docker-workdir /app`
- `--docker-codex-home-root /home/app/codex-home/workspace` (used by `cos resume` to resolve app chat thread ids)
- `cos resume --last` to continue the most recent interactive Codex session
- `--system-prompt-file ~/.cos/system.md`
- `--dangerous`
- `--terminal-theme green` to force green terminal styling during Codex run (best effort, default)

## Config

`cos` resolves settings with this precedence:
`default < global config < local config < environment < CLI option`

Config files:
- global: `~/.cos/config.toml`
- repo-local: `./.cos/config.toml` (or `<--repo>/.cos/config.toml`)

Inspect and validate:
```bash
cos config show
cos config show --json
cos config validate
```

Example config file:
```toml
[cos]
codex_backend = "docker"
docker_container = "task-app"
docker_workdir = "/app"
docker_codex_binary = "codex"
docker_app_mcp_url = "http://mcp-tools:8090/mcp"
docker_codex_home_root = "/home/app/codex-home/workspace"
app_mcp_name = "task-management-tools"
app_mcp_url = "http://localhost:8091/mcp" # local backend default; auto replaced by docker_app_mcp_url when backend=docker and this value is not explicitly overridden
app_mcp_bearer_env = ""
system_prompt_file = "~/.cos/system.md"
sandbox = "workspace-write"
approval = "on-request"
terminal_theme = "green" # default; set to "default" to disable green forcing
model = ""
repo = ""
```

## Local Dev (without install)

```bash
./tools/cos/cos --help
```
