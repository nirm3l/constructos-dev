# COS CLI

`cos` is a thin wrapper around Codex with automatic application MCP injection.

Core behavior:
- injects your application MCP server by default (`task-management-tools`)
- prepends hidden wrapper instructions every run
- keeps Codex in control of implementation work (file edits, commands, tests)
- supports layered config (`~/.cos/config.toml` and `./.cos/config.toml`)

## Requirements

- Python 3.10+
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

# interactive with initial request
cos chat "Implement CI cache improvements and run tests"

# non-interactive execution
cos exec "Implement retry logic in notification worker"

# diagnostics
cos doctor
cos doctor --app-mcp-url https://example.com --json
```

Useful options:
- `--repo /path/to/repo`
- `--app-mcp-url http://localhost:8091/mcp`
- `--system-prompt-file ~/.cos/system.md`
- `--dangerous`

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
app_mcp_name = "task-management-tools"
app_mcp_url = "http://localhost:8091/mcp"
app_mcp_bearer_env = ""
system_prompt_file = "~/.cos/system.md"
sandbox = "workspace-write"
approval = "on-request"
model = ""
repo = ""
```

## Local Dev (without install)

```bash
./tools/cos/cos --help
```
